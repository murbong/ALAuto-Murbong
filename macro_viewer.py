import argparse
import copy
import datetime
import importlib
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import cv2
import numpy

from macro_engine.runtime import MacroRunner
from macro_engine.schema import MacroSchemaError, normalize_macro
from macro_engine.runtime_bootstrap import create_runtime_driver, load_runtime_config, write_traceback
from util.stats import Stats
from util.utils import Utils

def bgr_to_photoimage(image):
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    height, width = rgb.shape[:2]
    ppm_header = f"P6 {width} {height} 255\n".encode('ascii')
    ppm_data = ppm_header + rgb.tobytes()
    return tk.PhotoImage(data=ppm_data, format='PPM')


def load_bgr_image(path):
    try:
        data = numpy.fromfile(path, dtype=numpy.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


class MacroViewerApp(object):
    QUEUE_POLL_MS = 100

    def __init__(self, root, config, macro_path, runtime_args=None):
        self.root = root
        self.config = config
        self.macro_path = macro_path
        self.runtime_args = runtime_args or argparse.Namespace(config=None, debug=False, legacy=False)
        self.asset_keys = self._load_asset_keys()
        self.available_macro_files = self._list_macro_files()

        self.queue = queue.Queue()
        self.trace_command_queue = queue.Queue()
        self.trace_running = False
        self.trace_stop_requested = False
        self.trace_thread = None
        self.last_photo = None
        self.template_photo = None
        self.editor_template_photo = None
        self.last_frame = None
        self.last_region = None
        self.selected_preview_region = None
        self.last_overlay_regions = []
        self.current_image = '-'
        self.log_lines = []
        self.editor_refresh_after_id = None
        self.trace_current_macro_path = None
        self.preview_transform = None
        self.preview_pick_mode = None
        self.region_pick_active = False
        self.region_pick_path = None
        self.canvas_drag_start = None
        self.canvas_drag_rect_id = None
        self.editor_clipboard_nodes = []
        self.tree_drag_state = None
        self.editor_form_loading = False
        self.tooltip_window = None
        self.tooltip_after_id = None
        self.tooltip_text = None
        self.trace_runtime = {}
        self.trace_enabled_vars = {}

        self.root.title('ALAuto Macro Viewer')
        self.root.geometry('1760x1020')

        self._build_layout()
        self.root.after(self.QUEUE_POLL_MS, self._tick)

    def _build_layout(self):
        container = ttk.Frame(self.root, padding=10)
        container.pack(fill='both', expand=True)

        split = ttk.Panedwindow(container, orient='horizontal')
        split.pack(fill='both', expand=True)

        left = ttk.Frame(split, width=460)
        left.pack_propagate(False)

        right = ttk.Frame(split, width=920, height=760)
        right.pack_propagate(False)

        split.add(left, weight=0)
        split.add(right, weight=1)
        self.main_split = split

        top_bar = ttk.Frame(left)
        top_bar.pack(fill='x')
        ttk.Label(top_bar, text='Macro').pack(side='left')
        self.macro_var = tk.StringVar(value=self.macro_path)
        ttk.Entry(top_bar, textvariable=self.macro_var).pack(side='left', fill='x', expand=True, padx=(8, 8))
        ttk.Button(top_bar, text='Browse', command=self._browse_macro).pack(side='left')

        self.notebook = ttk.Notebook(left)
        self.notebook.pack(fill='both', expand=True, pady=(10, 0))

        self.trace_tab = ttk.Frame(self.notebook)
        self.editor_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.trace_tab, text='Trace')
        self.notebook.add(self.editor_tab, text='Editor')

        self._build_trace_tab()
        self._build_editor_tab()

        self.canvas = tk.Canvas(right, highlightthickness=0, bg='#111111', width=1100, height=800)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', self._on_canvas_resize)
        self.canvas.bind('<ButtonPress-1>', self._on_canvas_press)
        self.canvas.bind('<B1-Motion>', self._on_canvas_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_canvas_release)
        self.canvas.bind('<Motion>', self._on_canvas_motion)
        self.canvas.bind('<Leave>', self._on_canvas_leave)
        self.canvas_image_id = None
        self.canvas_text_id = None
        self._show_canvas_message('Preview hidden\nPress Refresh Preview.')

    def _build_trace_tab(self):
        controls = ttk.Frame(self.trace_tab)
        controls.pack(fill='x')
        self.trace_button_var = tk.StringVar(value='Start Trace')
        ttk.Button(controls, textvariable=self.trace_button_var, command=self._toggle_trace).pack(side='left')

        self.status_var = tk.StringVar(value='status: idle')
        self.step_var = tk.StringVar(value='step: -')
        self.image_var = tk.StringVar(value='image: -')
        self.result_var = tk.StringVar(value='result: -')
        self.probe_var = tk.StringVar(value='probe: -')
        self.cursor_var = tk.StringVar(value='cursor: -')

        info_panel = ttk.Frame(self.trace_tab)
        info_panel.pack(fill='x', pady=(10, 0))
        ttk.Label(info_panel, textvariable=self.status_var, wraplength=410).pack(anchor='w')
        ttk.Label(info_panel, textvariable=self.step_var, wraplength=410).pack(anchor='w', pady=(8, 0))
        ttk.Label(info_panel, textvariable=self.image_var, wraplength=410).pack(anchor='w', pady=(8, 0))
        ttk.Label(info_panel, textvariable=self.result_var, wraplength=410).pack(anchor='w', pady=(8, 0))
        ttk.Label(info_panel, textvariable=self.probe_var, wraplength=410).pack(anchor='w', pady=(8, 0))
        ttk.Label(info_panel, textvariable=self.cursor_var, wraplength=410).pack(anchor='w', pady=(8, 10))

        ttk.Label(info_panel, text='Current Template').pack(anchor='w')
        self.template_frame = tk.Frame(info_panel, height=196, bg='#1f2933', highlightbackground='#3f4c5a', highlightthickness=1)
        self.template_frame.pack(fill='x', pady=(4, 10))
        self.template_frame.pack_propagate(False)
        self.template_label = tk.Label(
            self.template_frame,
            anchor='center',
            bg='#1f2933',
            fg='#cbd5e1',
            font=('Consolas', 10)
        )
        self.template_label.pack(fill='both', expand=True)

        context_panel = ttk.LabelFrame(self.trace_tab, text='Enabled Toggles', padding=8)
        context_panel.pack(fill='x', pady=(0, 10))
        self.trace_context_status_var = tk.StringVar(value='Trace not running')
        ttk.Label(context_panel, textvariable=self.trace_context_status_var, wraplength=390).pack(anchor='w', pady=(0, 8))
        self.trace_enabled_container = ttk.Frame(context_panel)
        self.trace_enabled_container.pack(fill='x')

        log_panel = ttk.Frame(self.trace_tab)
        log_panel.pack(fill='both', expand=True)
        ttk.Label(log_panel, text='Execution Log').pack(anchor='w')
        self.log_box = tk.Text(log_panel, height=32, wrap='word')
        self.log_box.pack(fill='both', expand=True)
        self.log_box.configure(state='disabled')
        self.log_box.tag_configure('log_macro', foreground='#1d4ed8')
        self.log_box.tag_configure('log_step', foreground='#7c3aed')
        self.log_box.tag_configure('log_error', foreground='#b91c1c')
        self.log_box.tag_configure('log_found', foreground='#15803d')
        self.log_box.tag_configure('log_miss', foreground='#b45309')
        self.log_box.tag_configure('log_color', foreground='#0f766e')

    def _build_editor_tab(self):
        self.editor_data = None
        self.tree_paths = {}

        toolbar = ttk.Frame(self.editor_tab)
        toolbar.pack(fill='x')
        ttk.Button(toolbar, text='Open JSON', command=self._editor_open_file).pack(side='left')
        ttk.Button(toolbar, text='Save JSON', command=self._editor_save_file).pack(side='left', padx=(6, 0))
        ttk.Button(toolbar, text='Validate', command=self._editor_validate_json).pack(side='left', padx=(6, 0))
        ttk.Button(toolbar, text='Normalize JSON', command=self._editor_normalize_json).pack(side='left', padx=(6, 0))
        ttk.Button(toolbar, text='Validate Regions', command=self._editor_validate_regions).pack(side='left', padx=(6, 0))
        ttk.Button(toolbar, text='Refresh Preview', command=self._refresh_preview).pack(side='left', padx=(6, 0))
        ttk.Button(toolbar, text='Refresh Tree', command=self._refresh_editor_structure).pack(side='left', padx=(6, 0))

        self.editor_path_var = tk.StringVar(value=self.macro_path)
        self.editor_status_var = tk.StringVar(value='Ready')
        ttk.Label(self.editor_tab, textvariable=self.editor_path_var, wraplength=410).pack(anchor='w', pady=(8, 4))
        ttk.Label(self.editor_tab, textvariable=self.editor_status_var, wraplength=410).pack(anchor='w', pady=(0, 8))

        editor_split = ttk.Panedwindow(self.editor_tab, orient='horizontal')
        editor_split.pack(fill='both', expand=True)

        tree_panel = ttk.Frame(editor_split)
        form_panel = ttk.Frame(editor_split)
        editor_split.add(tree_panel, weight=3)
        editor_split.add(form_panel, weight=2)

        tree_wrap = ttk.Frame(tree_panel)
        tree_wrap.pack(fill='both', expand=True)

        self.structure = ttk.Treeview(tree_wrap, show='tree', height=18, selectmode='extended')
        self.structure.column('#0', width=320, stretch=True)
        tree_scroll = ttk.Scrollbar(tree_wrap, orient='vertical', command=self.structure.yview)
        self.structure.configure(yscrollcommand=tree_scroll.set)
        self.structure.pack(side='left', fill='both', expand=True)
        tree_scroll.pack(side='right', fill='y')
        self.structure.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.structure.bind('<Button-3>', self._on_tree_context_menu)
        self.structure.bind('<ButtonPress-1>', self._on_tree_drag_start, add='+')
        self.structure.bind('<B1-Motion>', self._on_tree_drag_motion, add='+')
        self.structure.bind('<ButtonRelease-1>', self._on_tree_drag_release, add='+')
        self.structure.bind('<Control-c>', self._copy_selected_nodes, add='+')
        self.structure.bind('<Control-C>', self._copy_selected_nodes, add='+')
        self.structure.bind('<Control-v>', self._paste_selected_nodes, add='+')
        self.structure.bind('<Control-V>', self._paste_selected_nodes, add='+')
        self.structure.bind('<Delete>', self._delete_selected_node, add='+')

        self.editor_context_menu = tk.Menu(self.structure, tearoff=0)

        form_canvas = tk.Canvas(form_panel, highlightthickness=0)
        form_scroll = ttk.Scrollbar(form_panel, orient='vertical', command=form_canvas.yview)
        form_canvas.configure(yscrollcommand=form_scroll.set)
        form_canvas.pack(side='left', fill='both', expand=True)
        form_scroll.pack(side='right', fill='y')

        form_stack = ttk.Frame(form_canvas)
        self.form_window_id = form_canvas.create_window((0, 0), window=form_stack, anchor='nw')
        self.form_canvas = form_canvas
        self.form_stack = form_stack
        self.form_stack.bind('<Configure>', self._on_form_stack_configure)
        self.form_canvas.bind('<Configure>', self._on_form_canvas_configure)
        self.root.bind_all('<MouseWheel>', self._on_form_mousewheel, add='+')
        self.root.bind_all('<Button-4>', self._on_form_mousewheel_linux, add='+')
        self.root.bind_all('<Button-5>', self._on_form_mousewheel_linux, add='+')

        form = ttk.LabelFrame(form_stack, text='Selected Node', padding=8)
        form.pack(fill='x', pady=(0, 8))
        self.selected_path_var = tk.StringVar(value='path: -')
        ttk.Label(form, textvariable=self.selected_path_var, wraplength=290).pack(anchor='w')
        self.editor_help_var = tk.StringVar(value='Select a node to edit it. For step lists, use Quick Add and Move buttons.')
        ttk.Label(form, textvariable=self.editor_help_var, wraplength=290).pack(anchor='w', pady=(4, 0))
        self.editor_form_mode_var = tk.StringVar(value='Form: generic')
        ttk.Label(form, textvariable=self.editor_form_mode_var).pack(anchor='w', pady=(6, 0))

        self.editor_detail_container = ttk.Frame(form)
        self.editor_detail_container.pack(fill='x', pady=(8, 0))

        self.step_form = ttk.Frame(self.editor_detail_container)
        self.condition_form = ttk.Frame(self.editor_detail_container)
        self.generic_form = ttk.Frame(self.editor_detail_container)

        self.step_action_var = tk.StringVar()
        self.step_target_var = tk.StringVar()
        self.step_extra_var = tk.StringVar()
        self.step_into_var = tk.StringVar()
        self.step_target_label_var = tk.StringVar(value='Target')
        self.step_extra_label_var = tk.StringVar(value='Extra')
        self.step_form_hint_var = tk.StringVar(value='Select an action to see relevant fields.')

        ttk.Label(self.step_form, text='Action').pack(anchor='w')
        self.step_action_combo = ttk.Combobox(
            self.step_form,
            textvariable=self.step_action_var,
            state='readonly',
            values=self._step_action_options()
        )
        self.step_action_combo.pack(fill='x')
        self.step_action_combo.bind('<<ComboboxSelected>>', self._on_step_action_changed)
        self._bind_form_scroll_passthrough(self.step_action_combo)
        ttk.Label(self.step_form, textvariable=self.step_form_hint_var, wraplength=290).pack(anchor='w', pady=(6, 0))
        self.step_fields_frame = ttk.Frame(self.step_form)
        self.step_fields_frame.pack(fill='x', pady=(8, 0))
        self.step_field_specs = self._step_field_specs()
        self.step_field_vars, self.step_field_rows, self.step_field_widgets = self._build_labeled_field_rows(
            self.step_fields_frame,
            self.step_field_specs,
        )
        self.step_field_labels = {field_name: label_text for field_name, label_text, _ in self.step_field_specs}
        self.step_image_button_row = ttk.Frame(self.step_form)
        self.step_image_button_row.pack(fill='x', pady=(8, 0))
        self.add_step_image_button = ttk.Button(self.step_image_button_row, text='Add Image', command=lambda: self._start_new_image_pick('step'))
        self.add_step_image_button.pack(side='left', fill='x', expand=True)
        self.pick_step_image_button = ttk.Button(self.step_image_button_row, text='Pick On Preview', command=self._start_image_pick, state='disabled')
        self.pick_step_image_button.pack(side='left', fill='x', expand=True, padx=(6, 0))
        self.step_image_button_row.pack_forget()
        self.step_loop_frame = ttk.LabelFrame(self.step_form, text='While Loop Settings', padding=8)
        ttk.Label(self.step_loop_frame, text='Max Iterations').pack(anchor='w')
        self.step_max_iterations_var = tk.StringVar()
        self.step_max_iterations_entry = ttk.Entry(self.step_loop_frame, textvariable=self.step_max_iterations_var)
        self.step_max_iterations_entry.pack(fill='x')
        ttk.Label(self.step_loop_frame, text='Empty uses runtime default 1000.', wraplength=290).pack(anchor='w', pady=(6, 0))
        self.step_advanced_visible = False
        self.step_advanced_toggle = ttk.Button(self.step_form, text='Show Advanced Step JSON', command=lambda: self._toggle_advanced_editor('step'))
        self.step_advanced_toggle.pack(fill='x', pady=(8, 0))
        self.step_json_frame = ttk.Frame(self.step_form)
        ttk.Label(self.step_json_frame, text='Advanced Step JSON').pack(anchor='w')
        self.step_json_text = tk.Text(self.step_json_frame, height=6, wrap='word')
        self.step_json_text.pack(fill='x', pady=(6, 0))

        self.condition_type_var = tk.StringVar()
        self.condition_source_var = tk.StringVar(value='var')
        self.condition_key_var = tk.StringVar()
        self.condition_op_var = tk.StringVar(value='truthy')
        self.condition_value_var = tk.StringVar()
        self.condition_image_var = tk.StringVar()
        self.condition_region_var = tk.StringVar()
        self.condition_form_hint_var = tk.StringVar(value='Condition fields change based on condition type.')
        self.condition_items = []
        self.condition_item_index = None

        ttk.Label(self.condition_form, text='Condition Type').pack(anchor='w')
        self.condition_type_combo = ttk.Combobox(
            self.condition_form,
            textvariable=self.condition_type_var,
            state='readonly',
            values=['always', 'image', 'compare', 'not', 'all', 'any', 'region_color', 'plugin']
        )
        self.condition_type_combo.pack(fill='x')
        self.condition_type_combo.bind('<<ComboboxSelected>>', self._on_condition_type_changed)
        self._bind_form_scroll_passthrough(self.condition_type_combo)
        ttk.Label(self.condition_form, textvariable=self.condition_form_hint_var, wraplength=290).pack(anchor='w', pady=(6, 0))
        self.condition_fields_frame = ttk.Frame(self.condition_form)
        self.condition_fields_frame.pack(fill='x', pady=(8, 0))
        self.condition_field_specs = self._condition_field_specs()
        self.condition_field_vars, self.condition_field_rows, self.condition_field_widgets = self._build_labeled_field_rows(
            self.condition_fields_frame,
            self.condition_field_specs,
        )
        self.condition_image_input = self.condition_field_widgets['image']
        self.condition_image_button_row = ttk.Frame(self.condition_form)
        self.condition_image_button_row.pack(fill='x', pady=(8, 0))
        self.add_condition_image_button = ttk.Button(self.condition_image_button_row, text='Add Image', command=lambda: self._start_new_image_pick('condition'))
        self.add_condition_image_button.pack(side='left', fill='x', expand=True)
        self.pick_condition_image_button = ttk.Button(self.condition_image_button_row, text='Pick On Preview', command=self._start_image_pick, state='disabled')
        self.pick_condition_image_button.pack(side='left', fill='x', expand=True, padx=(6, 0))
        self.condition_image_button_row.pack_forget()
        self.condition_source_combo = self.condition_field_widgets['source']
        self.condition_source_combo.configure(state='readonly', values=['var', 'runtime'])
        self.condition_source_combo.bind('<<ComboboxSelected>>', self._on_condition_type_changed)
        self.condition_key_combo = self.condition_field_widgets['key']
        self.condition_op_combo = self.condition_field_widgets['op']
        self.condition_op_combo.configure(state='readonly', values=['truthy', 'equals', 'not_equals', 'gt', 'gte', 'lt', 'lte'])
        self.condition_op_combo.bind('<<ComboboxSelected>>', self._on_condition_type_changed)
        self.condition_items_frame = ttk.LabelFrame(self.condition_form, text='Child Conditions', padding=8)
        self.condition_items_list = tk.Listbox(self.condition_items_frame, height=5, exportselection=False)
        self.condition_items_list.pack(fill='x')
        self.condition_items_list.bind('<<ListboxSelect>>', self._on_condition_item_select)
        condition_item_buttons = ttk.Frame(self.condition_items_frame)
        condition_item_buttons.pack(fill='x', pady=(8, 0))
        ttk.Button(condition_item_buttons, text='Add Image', command=lambda: self._add_condition_item('image')).pack(side='left', fill='x', expand=True)
        ttk.Button(condition_item_buttons, text='Add Compare', command=lambda: self._add_condition_item('compare')).pack(side='left', fill='x', expand=True, padx=(6, 0))
        ttk.Button(condition_item_buttons, text='Add Not', command=lambda: self._add_condition_item('not')).pack(side='left', fill='x', expand=True, padx=(6, 0))
        ttk.Button(condition_item_buttons, text='Add Region Color', command=lambda: self._add_condition_item('region_color')).pack(side='left', fill='x', expand=True, padx=(6, 0))
        ttk.Button(condition_item_buttons, text='Remove', command=self._remove_condition_item).pack(side='left', fill='x', expand=True, padx=(6, 0))
        self.condition_advanced_visible = False
        self.condition_advanced_toggle = ttk.Button(self.condition_form, text='Show Advanced Condition JSON', command=lambda: self._toggle_advanced_editor('condition'))
        self.condition_advanced_toggle.pack(fill='x', pady=(8, 0))
        self.condition_json_frame = ttk.Frame(self.condition_form)
        ttk.Label(self.condition_json_frame, text='Advanced Condition JSON').pack(anchor='w')
        self.condition_json_text = tk.Text(self.condition_json_frame, height=6, wrap='word')
        self.condition_json_text.pack(fill='x', pady=(6, 0))

        generic_key_label = ttk.Label(self.generic_form, text='Key')
        generic_key_label.pack(anchor='w')
        self.node_key_var = tk.StringVar()
        generic_key_entry = ttk.Entry(self.generic_form, textvariable=self.node_key_var)
        generic_key_entry.pack(fill='x')
        generic_type_label = ttk.Label(self.generic_form, text='Value Type')
        generic_type_label.pack(anchor='w', pady=(8, 0))
        self.node_type_var = tk.StringVar(value='string')
        self.node_type_combo = ttk.Combobox(self.generic_form, textvariable=self.node_type_var, state='readonly', values=['string', 'number', 'bool', 'null', 'json'])
        self.node_type_combo.pack(fill='x')
        self._bind_form_scroll_passthrough(self.node_type_combo)
        generic_value_label = ttk.Label(self.generic_form, text='Value')
        generic_value_label.pack(anchor='w', pady=(8, 0))
        self.node_value_text = tk.Text(self.generic_form, height=6, wrap='word')
        self.node_value_text.pack(fill='x')
        self.pick_region_button = ttk.Button(self.generic_form, text='Pick On Preview', command=self._start_region_pick, state='disabled')
        self.pick_region_button.pack(fill='x', pady=(8, 0))
        self.generic_form.pack(fill='x')
        self._attach_tooltip(generic_key_label, 'Dictionary key name for the selected node.')
        self._attach_tooltip(generic_key_entry, 'Dictionary key name for the selected node.')
        self._attach_tooltip(generic_type_label, 'How the raw value text should be parsed.')
        self._attach_tooltip(self.node_type_combo, 'How the raw value text should be parsed.')
        self._attach_tooltip(generic_value_label, 'Raw scalar, JSON object, or JSON array value.')
        self._attach_tooltip(self.node_value_text, 'Raw scalar, JSON object, or JSON array value.')
        self._attach_tooltip(self.pick_region_button, 'Capture a region from the preview for the selected region node.')

        action_row = ttk.Frame(form)
        action_row.pack(fill='x', pady=(8, 0))
        ttk.Button(action_row, text='Apply', command=self._apply_selected_node).pack(side='left', fill='x', expand=True)
        ttk.Button(action_row, text='Delete', command=self._delete_selected_node).pack(side='left', fill='x', expand=True, padx=(6, 0))

        move_row = ttk.Frame(form)
        move_row.pack(fill='x', pady=(6, 0))
        ttk.Button(move_row, text='Duplicate', command=self._duplicate_selected_node).pack(side='left', fill='x', expand=True)
        ttk.Button(move_row, text='Move Up', command=lambda: self._move_selected_node(-1)).pack(side='left', fill='x', expand=True, padx=(6, 0))
        ttk.Button(move_row, text='Move Down', command=lambda: self._move_selected_node(1)).pack(side='left', fill='x', expand=True, padx=(6, 0))

        preview_frame = ttk.LabelFrame(form_stack, text='Image Preview', padding=8)
        preview_frame.pack(fill='x')
        self.editor_image_var = tk.StringVar(value='image: -')
        ttk.Label(preview_frame, textvariable=self.editor_image_var, wraplength=290).pack(anchor='w')
        self.editor_template_label = tk.Label(preview_frame, anchor='center', width=320, height=180)
        self.editor_template_label.pack(fill='x', pady=(6, 0))

        self.step_action_var.trace_add('write', self._on_editor_image_field_changed)
        self.step_field_vars['image'].trace_add('write', self._on_editor_image_field_changed)
        self.condition_type_var.trace_add('write', self._on_editor_image_field_changed)
        self.condition_field_vars['image'].trace_add('write', self._on_editor_image_field_changed)

        self._editor_load_path(self.macro_path)

    def _on_form_stack_configure(self, _event=None):
        if hasattr(self, 'form_canvas'):
            self.form_canvas.configure(scrollregion=self.form_canvas.bbox('all'))

    def _on_form_canvas_configure(self, event):
        if hasattr(self, 'form_window_id'):
            self.form_canvas.itemconfigure(self.form_window_id, width=event.width)

    def _widget_belongs_to_form_panel(self, widget):
        current = widget
        while current is not None:
            if current == self.form_canvas or current == self.form_stack:
                return True
            current = getattr(current, 'master', None)
        return False

    def _should_scroll_form_panel(self, event):
        if not hasattr(self, 'form_canvas'):
            return False
        if str(self.notebook.select()) != str(self.editor_tab):
            return False
        return self._widget_belongs_to_form_panel(event.widget)

    def _on_form_mousewheel(self, event):
        if not self._should_scroll_form_panel(event):
            return
        delta = event.delta
        if delta == 0:
            return 'break'
        steps = max(1, int(abs(delta) / 120))
        direction = -1 if delta > 0 else 1
        self.form_canvas.yview_scroll(direction * steps, 'units')
        return 'break'

    def _on_form_mousewheel_linux(self, event):
        if not self._should_scroll_form_panel(event):
            return
        direction = -1 if event.num == 4 else 1
        self.form_canvas.yview_scroll(direction, 'units')
        return 'break'

    def _bind_form_scroll_passthrough(self, widget):
        widget.bind('<MouseWheel>', self._on_form_mousewheel_passthrough)
        widget.bind('<Button-4>', self._on_form_mousewheel_linux_passthrough)
        widget.bind('<Button-5>', self._on_form_mousewheel_linux_passthrough)

    def _step_action_options(self):
        return [
            'tap_image', 'tap_found_image', 'tap_region', 'sleep', 'wait_update_screen',
            'update_screen', 'if', 'while', 'wait_for', 'repeat', 'run_macro', 'call',
            'set', 'increment', 'return', 'log', 'back', 'continue', 'break',
            'print_stats', 'swipe'
        ]

    def _step_field_specs(self):
        return [
            ('image', 'Image', 'combobox'),
            ('similarity', 'Similarity', 'combobox'),
            ('color', 'Color', 'combobox'),
            ('interrupt_if_not_found', 'Interrupt If Not Found', 'combobox'),
            ('region', 'Region', 'combobox'),
            ('seconds', 'Seconds', 'entry'),
            ('flex', 'Flex', 'entry'),
            ('path', 'Macro Path', 'combobox'),
            ('routine', 'Routine', 'combobox'),
            ('var', 'Variable', 'combobox'),
            ('value', 'Value', 'entry'),
            ('amount', 'Amount', 'entry'),
            ('times', 'Times', 'entry'),
            ('message', 'Message', 'entry'),
            ('plugin', 'Plugin', 'entry'),
            ('variables_json', 'Variables JSON', 'entry'),
            ('payload_json', 'Payload JSON', 'entry'),
            ('method', 'Stats Method', 'combobox'),
            ('oil_limit', 'Oil Limit', 'entry'),
            ('from_json', 'From (JSON)', 'entry'),
            ('to_json', 'To (JSON)', 'entry'),
            ('duration_ms', 'Duration ms', 'entry'),
            ('timeout', 'Timeout', 'entry'),
            ('poll_seconds', 'Poll Seconds', 'entry'),
            ('into', 'Store Result Into', 'entry'),
        ]

    def _condition_field_specs(self):
        return [
            ('image', 'Image', 'combobox'),
            ('similarity', 'Similarity', 'combobox'),
            ('color', 'Color', 'combobox'),
            ('interrupt_if_not_found', 'Interrupt If Not Found', 'combobox'),
            ('x_between', 'X Range JSON', 'entry'),
            ('y_between', 'Y Range JSON', 'entry'),
            ('source', 'Compare Source', 'combobox'),
            ('key', 'Key', 'combobox'),
            ('op', 'Operator', 'combobox'),
            ('value', 'Value', 'entry'),
            ('region', 'Region JSON', 'entry'),
            ('channel', 'Color Channel', 'entry'),
            ('match_low', 'Match Low JSON', 'entry'),
            ('match_high', 'Match High JSON', 'entry'),
            ('plugin', 'Plugin', 'entry'),
            ('payload_json', 'Payload JSON', 'entry'),
        ]

    def _step_field_tooltips(self):
        return {
            'image': 'Asset key without .png extension. Example: menu/confirm',
            'similarity': 'Image match threshold. Higher is stricter.',
            'color': 'Use color matching instead of grayscale matching.',
            'interrupt_if_not_found': 'If true, stop this image action when the image is not found.',
            'region': 'Named region key from the macro regions section.',
            'seconds': 'Delay or wait duration in seconds.',
            'flex': 'Optional random extra delay added to seconds.',
            'path': 'Macro JSON path to run.',
            'routine': 'Routine name from this macro file.',
            'var': 'Variable name stored in runtime context.',
            'value': 'Literal value or JSON ref object.',
            'amount': 'Amount added when increment runs.',
            'times': 'How many times repeat should run child steps.',
            'message': 'Log message. Supports {{var}} placeholders.',
            'plugin': 'Plugin module name to execute.',
            'variables_json': 'JSON object passed as variables to the child macro.',
            'payload_json': 'Extra JSON fields merged into the plugin step.',
            'method': 'Stats method name to call.',
            'oil_limit': 'Oil limit number or ref object used by print_stats.',
            'from_json': 'Swipe start point JSON. Example: {"x":960,"y":680}',
            'to_json': 'Swipe end point JSON. Example: {"x":1200,"y":680}',
            'duration_ms': 'Swipe duration in milliseconds.',
            'timeout': 'Maximum wait time in seconds.',
            'poll_seconds': 'Delay between condition checks in seconds.',
            'into': 'Optional variable name to store the result into.',
        }

    def _condition_field_tooltips(self):
        return {
            'image': 'Asset key without .png extension. Example: menu/confirm',
            'similarity': 'Image match threshold. Higher is stricter.',
            'color': 'Use color matching instead of grayscale matching.',
            'interrupt_if_not_found': 'If true, stop the image lookup early when not found.',
            'x_between': 'Optional JSON or value constraining matched X positions.',
            'y_between': 'Optional JSON or value constraining matched Y positions.',
            'source': 'Comparison source: runtime data or a variable.',
            'key': 'Lookup key inside the selected comparison source.',
            'op': 'Comparison operator.',
            'value': 'Comparison value or region-color threshold value.',
            'region': 'Region JSON object like {"x":0,"y":0,"w":100,"h":100}',
            'channel': 'Color channel index. Usually 0=B, 1=G, 2=R.',
            'match_low': 'Lower bound array for color matching.',
            'match_high': 'Upper bound array for color matching.',
            'plugin': 'Plugin module name to evaluate.',
            'payload_json': 'Extra JSON fields merged into the plugin condition.',
        }

    def _current_runtime_keys(self):
        if not isinstance(self.editor_data, dict):
            return []

        keys = []

        def visit(prefix, value):
            if isinstance(value, dict):
                for child_key, child_value in value.items():
                    child_prefix = '{}.{}'.format(prefix, child_key) if prefix else child_key
                    keys.append(child_prefix)
                    visit(child_prefix, child_value)

        visit('', self.editor_data.get('runtime') or {})
        return sorted(set(keys))

    def _build_labeled_field_rows(self, parent, field_specs):
        field_vars = {}
        field_rows = {}
        field_widgets = {}
        tooltip_map = {}
        if parent == getattr(self, 'step_fields_frame', None):
            tooltip_map = self._step_field_tooltips()
        elif parent == getattr(self, 'condition_fields_frame', None):
            tooltip_map = self._condition_field_tooltips()
        for field_name, label_text, widget_kind in field_specs:
            row = ttk.Frame(parent)
            label = ttk.Label(row, text=label_text)
            label.pack(anchor='w')
            var = tk.StringVar()
            if widget_kind == 'combobox':
                widget = ttk.Combobox(row, textvariable=var)
                self._bind_form_scroll_passthrough(widget)
            else:
                widget = ttk.Entry(row, textvariable=var)
            widget.pack(fill='x')
            tooltip_text = tooltip_map.get(field_name)
            if tooltip_text:
                self._attach_tooltip(label, tooltip_text)
                self._attach_tooltip(widget, tooltip_text)
            field_vars[field_name] = var
            field_rows[field_name] = row
            field_widgets[field_name] = widget
        return field_vars, field_rows, field_widgets

    def _attach_tooltip(self, widget, text):
        widget.bind('<Enter>', lambda event, tooltip_text=text: self._schedule_tooltip(event, tooltip_text), add='+')
        widget.bind('<Leave>', self._hide_tooltip, add='+')
        widget.bind('<ButtonPress>', self._hide_tooltip, add='+')

    def _schedule_tooltip(self, event, text):
        self._hide_tooltip()
        self.tooltip_text = text
        self.tooltip_after_id = self.root.after(350, lambda: self._show_tooltip(event.widget, text))

    def _show_tooltip(self, widget, text):
        self._hide_tooltip()
        if not text:
            return
        x = widget.winfo_rootx() + 16
        y = widget.winfo_rooty() + widget.winfo_height() + 8
        self.tooltip_window = tk.Toplevel(self.root)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f'+{x}+{y}')
        label = tk.Label(
            self.tooltip_window,
            text=text,
            justify='left',
            relief='solid',
            borderwidth=1,
            background='#fff8dc',
            foreground='#202020',
            padx=8,
            pady=5,
            wraplength=280,
        )
        label.pack()

    def _hide_tooltip(self, _event=None):
        if self.tooltip_after_id is not None:
            self.root.after_cancel(self.tooltip_after_id)
            self.tooltip_after_id = None
        if self.tooltip_window is not None:
            self.tooltip_window.destroy()
            self.tooltip_window = None

    def _on_form_mousewheel_passthrough(self, event):
        if not self._should_scroll_form_panel(event):
            return
        delta = event.delta
        if delta == 0:
            return 'break'
        steps = max(1, int(abs(delta) / 120))
        direction = -1 if delta > 0 else 1
        self.form_canvas.yview_scroll(direction * steps, 'units')
        return 'break'

    def _on_form_mousewheel_linux_passthrough(self, event):
        if not self._should_scroll_form_panel(event):
            return
        direction = -1 if event.num == 4 else 1
        self.form_canvas.yview_scroll(direction, 'units')
        return 'break'

    def _browse_macro(self):
        path = filedialog.askopenfilename(
            title='Select macro JSON',
            filetypes=[('JSON files', '*.json'), ('All files', '*.*')]
        )
        if not path:
            return
        self.macro_path = path
        self.macro_var.set(path)
        self._editor_load_path(path)

    def _editor_open_file(self):
        path = filedialog.askopenfilename(title='Open macro JSON', filetypes=[('JSON files', '*.json'), ('All files', '*.*')])
        if path:
            self._editor_load_path(path)

    def _sync_macro_runtime(self, path):
        normalized_path = os.path.abspath(path)
        self.macro_path = normalized_path
        self.macro_var.set(normalized_path)
        self.editor_path_var.set(normalized_path)
        self.config = load_runtime_config(self.runtime_args, normalized_path)
        self._set_trace_context_snapshot({'runtime': self._runtime_snapshot_from_value(self.config)})
        if not self.trace_running:
            self.trace_context_status_var.set('Loaded enabled flags from runtime')

    def _editor_load_path(self, path):
        with open(path, 'r', encoding='utf-8-sig') as handle:
            self.editor_data = normalize_macro(json.load(handle))
        self._sync_macro_runtime(path)
        self.editor_status_var.set('Loaded {}'.format(self.macro_path))
        self.available_macro_files = self._list_macro_files()
        self._set_editor_image_preview(None)
        self._refresh_editor_structure()

    def _on_tree_context_menu(self, event):
        item = self.structure.identify_row(event.y)
        if item:
            self.structure.selection_set(item)
            self.structure.focus(item)
            self._on_tree_select()
        self._rebuild_editor_context_menu()
        try:
            self.editor_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.editor_context_menu.grab_release()

    def _editor_save_file(self):
        path = self.editor_path_var.get().strip()
        if not path or self.editor_data is None:
            return
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(self.editor_data, handle, ensure_ascii=False, indent=2)
        self._sync_macro_runtime(path)
        self.editor_status_var.set('Saved {}'.format(self.macro_path))

    def _set_editor_runtime_value(self, key, value):
        if self.editor_data is None:
            return False
        runtime = self.editor_data.setdefault('runtime', {})
        self._set_nested_runtime_value(runtime, key, value)
        return True

    def _set_nested_runtime_value(self, target, path, value):
        parts = [part for part in str(path).split('.') if part]
        if not parts:
            return
        current = target
        for part in parts[:-1]:
            next_value = current.get(part)
            if not isinstance(next_value, dict):
                next_value = {}
                current[part] = next_value
            current = next_value
        current[parts[-1]] = value

    def _persist_enabled_toggle(self, key, value):
        path = self.editor_path_var.get().strip()
        if not path or not self._set_editor_runtime_value(key, value):
            return False
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(self.editor_data, handle, ensure_ascii=False, indent=2)
        self._sync_macro_runtime(path)
        self.editor_status_var.set('Saved {}'.format(self.macro_path))
        return True

    def _editor_validate_json(self):
        if self.editor_data is None:
            return
        MacroRunner(None, None).validate_macro(self.editor_data)
        self.editor_status_var.set('Validation passed')

    def _rebuild_editor_context_menu(self):
        self.editor_context_menu.delete(0, tk.END)
        if self.editor_data is None:
            return

        selection = self.structure.selection()
        path_parts = self.tree_paths.get(selection[0], []) if selection else []
        value = self._get_by_path(path_parts) if selection else self.editor_data
        add_count = 0

        if self._can_add_region_here(path_parts, value):
            self.editor_context_menu.add_command(label='Add Region', command=self._add_region_node)
            add_count += 1
        if self._can_add_routine_here(path_parts, value):
            self.editor_context_menu.add_command(label='Add Routine', command=self._add_routine_node)
            add_count += 1
        if self._can_add_step_here(path_parts, value):
            add_menu = tk.Menu(self.editor_context_menu, tearoff=0)
            for group_name, template_names in self._step_template_groups():
                group_menu = tk.Menu(add_menu, tearoff=0)
                for template_name in template_names:
                    group_menu.add_command(
                        label=template_name,
                        command=lambda name=template_name: self._quick_add_step_template(name)
                    )
                add_menu.add_cascade(label=group_name, menu=group_menu)
            self.editor_context_menu.add_cascade(label='Add Step', menu=add_menu)
            add_count += 1
        if self._can_add_then_step_here(path_parts, value):
            self.editor_context_menu.add_command(label='Add Then Step', command=lambda: self._add_step_branch_item('steps'))
            add_count += 1
        if self._can_add_else_branch_here(path_parts, value):
            self.editor_context_menu.add_command(label='Add Else Branch', command=self._ensure_else_branch)
            add_count += 1
        if self._can_add_timeout_branch_here(path_parts, value):
            self.editor_context_menu.add_command(label='Add Timeout Branch', command=self._ensure_timeout_branch)
            add_count += 1
        if self._can_add_timeout_step_here(path_parts, value):
            self.editor_context_menu.add_command(label='Add Timeout Step', command=lambda: self._add_step_branch_item('timeout_steps'))
            add_count += 1
        if self._can_add_condition_here(path_parts, value):
            condition_menu = tk.Menu(self.editor_context_menu, tearoff=0)
            for condition_type in ('image', 'compare', 'region_color', 'plugin', 'not', 'all', 'any', 'always'):
                condition_menu.add_command(
                    label=condition_type,
                    command=lambda name=condition_type: self._replace_selected_condition(name)
                )
            self.editor_context_menu.add_cascade(label='Set Condition', menu=condition_menu)
            add_count += 1
        if self._can_add_child_here(value):
            self.editor_context_menu.add_command(label='Add Child Field', command=self._add_child_node)
            add_count += 1

        if add_count:
            self.editor_context_menu.add_separator()

        self.editor_context_menu.add_command(label='Duplicate', command=self._duplicate_selected_node)
        self.editor_context_menu.add_command(label='Move Up', command=lambda: self._move_selected_node(-1))
        self.editor_context_menu.add_command(label='Move Down', command=lambda: self._move_selected_node(1))
        self.editor_context_menu.add_command(label='Delete', command=self._delete_selected_node)

    def _step_template_groups(self):
        return [
            ('Basic', ['log', 'sleep', 'update_screen', 'wait_update_screen', 'back', 'swipe']),
            ('Input', ['tap_image', 'tap_found_image', 'tap_region']),
            ('Flow', ['if_image', 'if_not_battle', 'while_true', 'wait_for_image', 'repeat', 'continue', 'break', 'return']),
            ('Data', ['set', 'increment', 'stats_increment', 'print_stats']),
            ('Macro', ['call_routine', 'run_macro', 'plugin'])
        ]

    def _can_add_child_here(self, value):
        return isinstance(value, (dict, list))

    def _can_add_region_here(self, path_parts, value):
        return isinstance(value, dict) and (path_parts == [] or path_parts == ['regions'])

    def _can_add_routine_here(self, path_parts, value):
        return isinstance(value, dict) and (path_parts == [] or path_parts == ['routines'])

    def _is_step_list_path(self, path_parts, value):
        if not isinstance(value, list):
            return False
        if path_parts == ['steps']:
            return True
        if len(path_parts) == 2 and path_parts[0] == 'routines':
            return True
        return bool(path_parts and path_parts[-1] in ('steps', 'else_steps', 'timeout_steps'))

    def _selected_step_dict(self, path_parts, value):
        if isinstance(value, dict) and 'action' in value:
            return value
        parent_info = self._get_parent_info(path_parts)
        if parent_info and parent_info[1] == 'list':
            parent_path = path_parts[:-1]
            parent_value = self._get_by_path(parent_path) if parent_path else self.editor_data
            if self._is_step_list_path(parent_path, parent_value):
                return value if isinstance(value, dict) and 'action' in value else None
        return None

    def _can_add_step_here(self, path_parts, value):
        if path_parts == [] and isinstance(value, dict):
            return True
        if self._is_step_list_path(path_parts, value):
            return True
        step = self._selected_step_dict(path_parts, value)
        return step is not None

    def _can_add_then_step_here(self, path_parts, value):
        step = self._selected_step_dict(path_parts, value)
        return bool(step and step.get('action') in ('if', 'while', 'wait_for', 'repeat'))

    def _can_add_else_branch_here(self, path_parts, value):
        step = self._selected_step_dict(path_parts, value)
        return bool(step and step.get('action') == 'if' and 'else_steps' not in step)

    def _can_add_timeout_branch_here(self, path_parts, value):
        step = self._selected_step_dict(path_parts, value)
        return bool(step and step.get('action') == 'wait_for' and 'timeout_steps' not in step)

    def _can_add_timeout_step_here(self, path_parts, value):
        step = self._selected_step_dict(path_parts, value)
        return bool(step and step.get('action') == 'wait_for' and 'timeout_steps' in step)

    def _can_add_condition_here(self, path_parts, value):
        return isinstance(value, dict) and ((value.get('type') is not None) or (value.get('action') in ('if', 'while', 'wait_for')))

    def _add_region_node(self):
        if self.editor_data is None:
            return
        regions = self.editor_data.setdefault('regions', {})
        name = self._prompt_new_key('Add Region', 'Region name:', regions)
        if not name:
            self.editor_status_var.set('Add region cancelled')
            return
        regions[name] = {'x': 0, 'y': 0, 'w': 0, 'h': 0}
        self.editor_status_var.set('Region added')
        self._refresh_editor_structure()
        self._select_tree_path(['regions', name])

    def _add_routine_node(self):
        if self.editor_data is None:
            return
        routines = self.editor_data.setdefault('routines', {})
        name = self._prompt_new_key('Add Routine', 'Routine name:', routines)
        if not name:
            self.editor_status_var.set('Add routine cancelled')
            return
        routines[name] = []
        self.editor_status_var.set('Routine added')
        self._refresh_editor_structure()
        self._select_tree_path(['routines', name])

    def _prompt_new_key(self, title, prompt, existing_dict):
        name = simpledialog.askstring(title, prompt, parent=self.root)
        if not name:
            return None
        name = name.strip()
        if not name:
            return None
        if name in existing_dict:
            messagebox.showerror(title, '{} already exists'.format(name), parent=self.root)
            return None
        return name

    def _add_step_branch_item(self, branch_key):
        selection = self.structure.selection()
        if not selection or self.editor_data is None:
            return
        path_parts = self.tree_paths.get(selection[0], [])
        value = self._get_by_path(path_parts)
        step = self._selected_step_dict(path_parts, value)
        if not step:
            self.editor_status_var.set('Select a step first')
            return
        step.setdefault(branch_key, [])
        step[branch_key].append(self._build_step_template('tap_image'))
        self.editor_status_var.set('Added {} item'.format(branch_key))
        self._refresh_editor_structure()
        self._select_tree_path(path_parts + [branch_key, len(step[branch_key]) - 1])

    def _ensure_else_branch(self):
        self._ensure_step_branch('else_steps', 'Else branch added')

    def _ensure_timeout_branch(self):
        self._ensure_step_branch('timeout_steps', 'Timeout branch added')

    def _ensure_step_branch(self, branch_key, status_text):
        selection = self.structure.selection()
        if not selection or self.editor_data is None:
            return
        path_parts = self.tree_paths.get(selection[0], [])
        value = self._get_by_path(path_parts)
        step = self._selected_step_dict(path_parts, value)
        if not step:
            self.editor_status_var.set('Select a step first')
            return
        step.setdefault(branch_key, [])
        self.editor_status_var.set(status_text)
        self._refresh_editor_structure()
        self._select_tree_path(path_parts + [branch_key])

    def _replace_selected_condition(self, condition_type):
        selection = self.structure.selection()
        if not selection or self.editor_data is None:
            return
        path_parts = self.tree_paths.get(selection[0], [])
        value = self._get_by_path(path_parts)
        if isinstance(value, dict) and value.get('action') in ('if', 'while', 'wait_for'):
            value['condition'] = self._build_condition_template(condition_type)
            target_path = path_parts + ['condition']
        elif isinstance(value, dict) and value.get('type') is not None:
            parent_info = self._get_parent_info(path_parts)
            if not parent_info:
                return
            parent, parent_type = parent_info
            replacement = self._build_condition_template(condition_type)
            if parent_type == 'dict':
                parent[path_parts[-1]] = replacement
            else:
                parent[path_parts[-1]] = replacement
            target_path = path_parts
        else:
            self.editor_status_var.set('Select a condition or conditional step first')
            return
        self.editor_status_var.set('Condition updated')
        self._refresh_editor_structure()
        self._select_tree_path(target_path)

    def _build_condition_template(self, condition_type):
        templates = {
            'always': {'type': 'always', 'value': True},
            'image': {'type': 'image', 'image': 'menu/confirm'},
            'compare': {'type': 'compare', 'source': 'var', 'key': '', 'op': 'truthy'},
            'region_color': {'type': 'region_color', 'region': {'x': 0, 'y': 0, 'w': 1, 'h': 1}, 'op': 'equals', 'value': [0, 0, 0]},
            'plugin': {'type': 'plugin', 'plugin': 'headquarters.check_dorm_notice'},
            'not': {'type': 'not', 'item': {'type': 'image', 'image': 'menu/confirm'}},
            'all': {'type': 'all', 'items': [{'type': 'image', 'image': 'menu/confirm'}]},
            'any': {'type': 'any', 'items': [{'type': 'image', 'image': 'menu/confirm'}]}
        }
        return copy.deepcopy(templates[condition_type])
        messagebox.showinfo('Validation Passed', 'Macro structure is valid.')

    def _editor_normalize_json(self):
        if self.editor_data is None:
            return
        try:
            self.editor_data = normalize_macro(self.editor_data)
        except MacroSchemaError as error:
            messagebox.showerror('Normalize Failed', str(error))
            self.editor_status_var.set('Normalize failed')
            return
        self.editor_status_var.set('Normalized to standard schema')
        self._refresh_editor_structure()

    def _editor_validate_regions(self):
        if not isinstance(self.editor_data, dict):
            return
        regions = self.editor_data.get('regions') or {}
        if not regions:
            self.editor_status_var.set('No regions in current macro')
            self.last_overlay_regions = []
            return
        frame = self._ensure_preview_frame()
        if frame is None:
            self.editor_status_var.set('Region validation failed: could not capture screen')
            return
        self.last_region = None
        overlays = [
            {
                'name': name,
                'x': region['x'],
                'y': region['y'],
                'w': region['w'],
                'h': region['h']
            }
            for name, region in regions.items()
            if isinstance(region, dict) and all(key in region for key in ('x', 'y', 'w', 'h'))
        ]
        overlays.extend(self._get_plugin_validation_regions())
        self.last_overlay_regions = overlays
        self._render_frame(self.last_frame, None)
        self.editor_status_var.set('Showing {} regions on preview'.format(len(self.last_overlay_regions)))

    def _get_plugin_validation_regions(self):
        plugin_regions = []
        if not isinstance(self.editor_data, dict):
            return plugin_regions
        plugin_names = set()

        def collect_plugins(steps):
            if not isinstance(steps, list):
                return
            for step in steps:
                if not isinstance(step, dict):
                    continue
                if step.get('action') == 'plugin' and step.get('plugin'):
                    plugin_names.add(step.get('plugin'))
                for key in ('steps', 'else_steps', 'timeout_steps'):
                    collect_plugins(step.get(key))

        collect_plugins(self.editor_data.get('steps'))
        for routine_steps in (self.editor_data.get('routines') or {}).values():
            collect_plugins(routine_steps)

        seen = set()
        for plugin_name in sorted(plugin_names):
            module_name, _, _ = str(plugin_name).rpartition('.')
            if not module_name or module_name in seen:
                continue
            seen.add(module_name)
            try:
                module = importlib.import_module('macro_plugins.{}'.format(module_name))
                module = importlib.reload(module)
                getter = getattr(module, 'get_validation_regions', None)
                if callable(getter):
                    for region in getter() or []:
                        if isinstance(region, dict) and all(key in region for key in ('name', 'x', 'y', 'w', 'h')):
                            plugin_regions.append(region)
            except Exception:
                pass
        return plugin_regions

    def _refresh_preview(self):
        self.editor_status_var.set('Refreshing preview...')
        if not self.trace_running:
            self.status_var.set('status: refreshing preview')
        self.root.update_idletasks()
        self.root.after_idle(self._refresh_preview_start)
        return None

    def _refresh_preview_start(self):
        self.root.update_idletasks()
        threading.Thread(target=self._refresh_preview_worker, daemon=True).start()
        self.root.after(50, self._rerender_last_frame)
        self.root.after(200, self._rerender_last_frame)
        self.root.after(500, self._rerender_last_frame)
        self.root.after(1000, self._rerender_last_frame)

    def _refresh_preview_worker(self):
        try:
            self._log_preview_debug('refresh worker start')
            frame = self._ensure_preview_frame(force=True, render=False)
            if frame is None:
                self._log_preview_debug('refresh worker failed: frame is None')
                self.queue.put({'type': 'preview_refresh_done', 'ok': False, 'error': 'frame is None'})
                return
            dump_path = self._write_preview_dump(frame)
            self._log_preview_debug('refresh worker ok: shape={} dump={}'.format(getattr(frame, 'shape', None), dump_path))
            self.queue.put({'type': 'preview_refresh_done', 'ok': True, 'shape': getattr(frame, 'shape', None), 'dump_path': dump_path, 'frame': frame.copy()})
        except Exception as error:
            self._log_preview_debug('refresh worker exception: {}'.format(error))
            self.queue.put({'type': 'preview_refresh_done', 'ok': False, 'error': str(error)})

    def _rerender_last_frame(self):
        if self.last_frame is not None:
            self._render_frame(self.last_frame, self.last_region)

    def _log_preview_debug(self, message):
        dump_dir = os.path.join(os.getcwd(), 'debug')
        os.makedirs(dump_dir, exist_ok=True)
        log_path = os.path.join(dump_dir, 'preview_refresh.log')
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
        with open(log_path, 'a', encoding='utf-8') as handle:
            handle.write('[{}] {}\n'.format(timestamp, message))

    def _write_preview_dump(self, frame):
        dump_dir = os.path.join(os.getcwd(), 'debug')
        os.makedirs(dump_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        dump_path = os.path.join(dump_dir, 'preview_{}.png'.format(timestamp))
        encoded, buffer = cv2.imencode('.png', frame)
        if encoded:
            buffer.tofile(dump_path)
            latest_path = os.path.join(dump_dir, 'preview_latest.png')
            buffer.tofile(latest_path)
            return latest_path
        return dump_path

    def _ensure_preview_frame(self, force=False, render=True):
        if self.last_frame is not None and not force:
            self._log_preview_debug('reuse cached frame')
            return self.last_frame

        frame = None
        for attempt in range(4):
            try:
                if attempt == 0:
                    self._log_preview_debug('attempt 0: Utils.update_screen()')
                    Utils.update_screen()
                    frame = getattr(Utils, 'color_screen', None)
                elif attempt in (1, 2):
                    self._log_preview_debug('attempt {}: Utils.wait_update_screen(0.3)'.format(attempt))
                    Utils.wait_update_screen(0.3)
                    frame = getattr(Utils, 'color_screen', None)
                else:
                    self._log_preview_debug('attempt 3: Utils.get_color_screen()')
                    frame = Utils.get_color_screen()
                    if frame is not None and getattr(frame, 'size', 0) > 0:
                        Utils.color_screen = frame
                        try:
                            Utils.screen = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        except Exception as error:
                            self._log_preview_debug('grayscale convert failed: {}'.format(error))
                self._log_preview_debug('attempt {} result: frame={} size={}'.format(attempt, frame is not None, getattr(frame, 'size', 0) if frame is not None else 0))
            except Exception as error:
                self._log_preview_debug('attempt {} exception: {}'.format(attempt, error))
                frame = None
                continue
            if frame is not None and getattr(frame, 'size', 0) > 0:
                break

        if frame is None or getattr(frame, 'size', 0) == 0:
            self._log_preview_debug('all attempts failed')
            return None

        self.last_frame = frame.copy()
        self._log_preview_debug('captured frame shape={}'.format(getattr(self.last_frame, 'shape', None)))
        if render:
            self._render_frame(self.last_frame, self.last_region)
        return self.last_frame

    def _refresh_editor_structure(self):
        open_paths = self._capture_tree_open_paths()
        self.structure.delete(*self.structure.get_children())
        self.tree_paths = {}
        if self.editor_data is None:
            return
        self._insert_tree('', 'root', self.editor_data, [])
        self._restore_tree_open_paths(open_paths)
        self._update_editor_actions_state()

    def _capture_tree_open_paths(self):
        open_paths = set()
        for item_id, item_path in self.tree_paths.items():
            if self.structure.item(item_id, 'open'):
                open_paths.add(tuple(item_path))
        if not open_paths:
            open_paths.add(())
        return open_paths

    def _restore_tree_open_paths(self, open_paths):
        for item_id, item_path in self.tree_paths.items():
            self.structure.item(item_id, open=tuple(item_path) in open_paths)

    def _insert_tree(self, parent, label, value, path_parts):
        node_text, node_value = self._describe_tree_node(label, value, path_parts)
        normalized_text = str(node_text).strip()
        normalized_value = str(node_value).strip() if node_value is not None else ''
        text = normalized_text
        if normalized_value and normalized_value != normalized_text and not normalized_text.endswith(normalized_value):
            text = '{}  -  {}'.format(normalized_text, normalized_value)
        node = self.structure.insert(parent, 'end', text=text)
        self.tree_paths[node] = list(path_parts)
        if isinstance(value, dict):
            for key, child in self._iter_visible_children(value):
                self._insert_tree(node, key, child, path_parts + [key])
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._insert_tree(node, index, child, path_parts + [index])
        return node

    def _on_tree_select(self, _event=None):
        selection = self.structure.selection()
        if not selection or self.editor_data is None:
            self.selected_preview_region = None
            self._set_editor_image_preview(None)
            if self.last_frame is not None:
                self._render_frame(self.last_frame, self.last_region)
            return
        if len(selection) > 1:
            self.selected_preview_region = None
            self.selected_path_var.set('path: {} nodes selected'.format(len(selection)))
            self.editor_form_mode_var.set('Form: multi-select')
            self.editor_help_var.set('Multiple nodes selected. You can drag, copy, paste, or delete items from the same list.')
            self._set_editor_image_preview(None)
            if self.last_frame is not None:
                self._render_frame(self.last_frame, self.last_region)
            self._update_editor_actions_state()
            return
        item = selection[0]
        path_parts = self.tree_paths.get(item, [])
        value = self._get_by_path(path_parts)
        self.selected_preview_region = self._resolve_selected_preview_region(path_parts, value)
        if self.last_frame is not None:
            self._render_frame(self.last_frame, self.last_region)
        self.selected_path_var.set('path: root' + ''.join('[{}]'.format(p) if isinstance(p, int) else '.' + str(p) for p in path_parts))
        parent_info = self._get_parent_info(path_parts)
        self.node_key_var.set(str(path_parts[-1]) if parent_info and parent_info[1] == 'dict' else '')
        if isinstance(value, dict) and 'action' in value:
            if value.get('action') in ('if', 'while', 'wait_for'):
                self._show_editor_form('step_condition')
                self._populate_step_form(value)
                self._populate_condition_form(value.get('condition', {}))
            else:
                self._show_editor_form('step')
                self._populate_step_form(value)
        elif isinstance(value, dict) and value.get('type'):
            self._show_editor_form('condition')
            self._populate_condition_form(value)
        else:
            self._show_editor_form('generic')
            self.node_type_var.set(self._infer_type_name(value))
            self.node_value_text.delete('1.0', tk.END)
            if isinstance(value, (dict, list)):
                self.node_value_text.insert('1.0', json.dumps(value, ensure_ascii=False, indent=2))
            elif value is None:
                self.node_value_text.insert('1.0', 'null')
            elif isinstance(value, bool):
                self.node_value_text.insert('1.0', 'true' if value else 'false')
            else:
                self.node_value_text.insert('1.0', str(value))
        self._refresh_editor_image_preview(path_parts, value)
        self._update_editor_actions_state()

    def _apply_selected_node(self):
        selection = self.structure.selection()
        if not selection or self.editor_data is None:
            return
        item = selection[0]
        path_parts = self.tree_paths.get(item, [])
        current_value = self._get_by_path(path_parts)
        if isinstance(current_value, dict) and 'action' in current_value:
            new_value = self._collect_step_form_value()
        elif isinstance(current_value, dict) and current_value.get('type'):
            new_value = self._collect_condition_form_value()
        else:
            new_value = self._parse_value_from_form(self.node_type_var.get(), self.node_value_text.get('1.0', tk.END).strip())
        parent_info = self._get_parent_info(path_parts)
        old_key = None
        new_key = None
        if not path_parts:
            self.editor_data = new_value
        elif parent_info and parent_info[1] == 'dict':
            parent, _ = parent_info[0], parent_info[1]
            old_key = path_parts[-1]
            new_key = self.node_key_var.get().strip() or old_key
            if new_key != old_key:
                parent[new_key] = new_value
                del parent[old_key]
            else:
                parent[old_key] = new_value
        elif parent_info and parent_info[1] == 'list':
            parent_info[0][path_parts[-1]] = new_value
        self.editor_status_var.set('Node updated')
        self._refresh_editor_structure()
        self._select_tree_path(path_parts[:-1] + [new_key] if path_parts and parent_info and parent_info[1] == 'dict' and new_key != old_key else path_parts)

    def _delete_selected_node(self, _event=None):
        selection = self.structure.selection()
        if not selection or self.editor_data is None:
            return 'break' if _event is not None else None
        if len(selection) > 1:
            if self._delete_multiple_selected_nodes():
                return 'break'
            return 'break' if _event is not None else None
        item = selection[0]
        path_parts = self.tree_paths.get(item, [])
        if not path_parts:
            self.editor_status_var.set('Cannot delete root')
            return 'break' if _event is not None else None
        parent, parent_type = self._get_parent_info(path_parts)
        key = path_parts[-1]
        if parent_type == 'dict':
            del parent[key]
        else:
            parent.pop(key)
        self.editor_status_var.set('Node deleted')
        self._refresh_editor_structure()
        self._select_tree_path(path_parts[:-1])
        return 'break' if _event is not None else None

    def _add_child_node(self):
        selection = self.structure.selection()
        if not selection or self.editor_data is None:
            return
        item = selection[0]
        path_parts = self.tree_paths.get(item, [])
        target = self._get_by_path(path_parts)
        if isinstance(target, dict):
            child_key = simpledialog.askstring('Add Child Field', 'Field name:', parent=self.root)
            if not child_key:
                self.editor_status_var.set('Add child cancelled')
                return
            value_raw = simpledialog.askstring('Add Child Field', 'Initial value (JSON or plain text):', parent=self.root)
            child_value = self._parse_loose_value(value_raw if value_raw is not None else '')
            target[child_key] = child_value
        elif isinstance(target, list):
            value_raw = simpledialog.askstring('Add List Item', 'Initial value (JSON or plain text):', parent=self.root)
            child_value = self._parse_loose_value(value_raw if value_raw is not None else '')
            target.append(child_value)
        else:
            self.editor_status_var.set('Select a dict or list node to add children')
            return
        self.editor_status_var.set('Child added')
        self._refresh_editor_structure()
        if isinstance(target, dict):
            self._select_tree_path(path_parts + [child_key])
        else:
            self._select_tree_path(path_parts + [len(target) - 1])

    def _duplicate_selected_node(self):
        selection = self.structure.selection()
        if not selection or self.editor_data is None:
            return
        item = selection[0]
        path_parts = self.tree_paths.get(item, [])
        if not path_parts:
            self.editor_status_var.set('Cannot duplicate root')
            return
        parent_info = self._get_parent_info(path_parts)
        if not parent_info or parent_info[1] != 'list':
            self.editor_status_var.set('Duplicate works for list items')
            return
        parent = parent_info[0]
        index = path_parts[-1]
        parent.insert(index + 1, copy.deepcopy(parent[index]))
        self.editor_status_var.set('Node duplicated')
        self._refresh_editor_structure()
        self._select_tree_path(path_parts[:-1] + [index + 1])

    def _move_selected_node(self, direction):
        selection = self.structure.selection()
        if not selection or self.editor_data is None:
            return
        selection_info = self._get_selected_list_item_info()
        if not selection_info:
            self.editor_status_var.set('Move works for list items from the same list')
            return
        parent = selection_info['parent']
        indices = selection_info['indices']
        if direction < 0:
            if indices[0] == 0:
                self.editor_status_var.set('Cannot move further')
                return
            moving_items = [parent[index] for index in indices]
            for index in indices:
                parent.pop(index)
            insert_at = indices[0] - 1
            for offset, value in enumerate(moving_items):
                parent.insert(insert_at + offset, value)
            new_indices = list(range(insert_at, insert_at + len(moving_items)))
        else:
            if indices[-1] >= len(parent) - 1:
                self.editor_status_var.set('Cannot move further')
                return
            moving_items = [parent[index] for index in indices]
            for index in reversed(indices):
                parent.pop(index)
            insert_at = indices[0] + 1
            for offset, value in enumerate(moving_items):
                parent.insert(insert_at + offset, value)
            new_indices = list(range(insert_at, insert_at + len(moving_items)))
        if not new_indices:
            self.editor_status_var.set('Cannot move further')
            return
        self.editor_status_var.set('Node moved')
        self._refresh_editor_structure()
        self._select_tree_paths([selection_info['parent_path'] + [index] for index in new_indices])

    def _quick_add_step_template(self, template_name=None):
        selection = self.structure.selection()
        if self.editor_data is None:
            return
        if not selection:
            path_parts = []
            target = self.editor_data
        else:
            item = selection[0]
            path_parts = self.tree_paths.get(item, [])
            target = self._get_by_path(path_parts)
        insert_path = list(path_parts)
        if path_parts == [] and isinstance(target, dict):
            target_list = target.setdefault('steps', [])
            insert_index = len(target_list)
            insert_path = ['steps']
        elif isinstance(target, list):
            target_list = target
            insert_index = len(target_list)
        else:
            parent_info = self._get_parent_info(path_parts)
            if not parent_info or parent_info[1] != 'list':
                self.editor_status_var.set('Quick Add works on list nodes or list items')
                return
            target_list = parent_info[0]
            insert_index = path_parts[-1] + 1
            insert_path = path_parts[:-1]

        template_name = template_name or 'tap_image'
        new_step = self._build_step_template(template_name)
        target_list.insert(insert_index, new_step)
        self.editor_status_var.set('Added {} step'.format(template_name))
        self._refresh_editor_structure()
        self._select_tree_path(insert_path + [insert_index])

    def _get_by_path(self, path_parts):
        current = self.editor_data
        for part in path_parts:
            current = current[part]
        return current

    def _get_parent_info(self, path_parts):
        if not path_parts:
            return None
        parent_path = path_parts[:-1]
        parent = self._get_by_path(parent_path) if parent_path else self.editor_data
        return parent, 'dict' if isinstance(parent, dict) else 'list'

    def _iter_visible_children(self, value):
        if not isinstance(value, dict):
            return []
        if 'action' in value:
            visible_keys = ['steps', 'else_steps', 'timeout_steps']
            return [(key, value[key]) for key in visible_keys if key in value]
        if value.get('type'):
            return []
        hidden_root_keys = {'name', 'description'}
        return [(key, child) for key, child in value.items() if key not in hidden_root_keys]

    def _show_editor_form(self, mode):
        self.step_form.pack_forget()
        self.condition_form.pack_forget()
        self.generic_form.pack_forget()
        if mode == 'step_condition':
            self.editor_form_mode_var.set('Form: step + condition')
            self.step_form.pack(fill='x')
            self.condition_form.pack(fill='x', pady=(8, 0))
            return
        if mode == 'step':
            self.editor_form_mode_var.set('Form: step')
            self.step_form.pack(fill='x')
            return
        if mode == 'condition':
            self.editor_form_mode_var.set('Form: condition')
            self.condition_form.pack(fill='x')
            return
        self.editor_form_mode_var.set('Form: generic')
        self.generic_form.pack(fill='x')

    def _toggle_advanced_editor(self, target):
        if target == 'step':
            self.step_advanced_visible = not self.step_advanced_visible
            if self.step_advanced_visible:
                self.step_json_frame.pack(fill='x', pady=(6, 0))
                self.step_advanced_toggle.configure(text='Hide Advanced Step JSON')
            else:
                self.step_json_frame.pack_forget()
                self.step_advanced_toggle.configure(text='Show Advanced Step JSON')
            return
        self.condition_advanced_visible = not self.condition_advanced_visible
        if self.condition_advanced_visible:
            self.condition_json_frame.pack(fill='x', pady=(6, 0))
            self.condition_advanced_toggle.configure(text='Hide Advanced Condition JSON')
        else:
            self.condition_json_frame.pack_forget()
            self.condition_advanced_toggle.configure(text='Show Advanced Condition JSON')

    def _populate_step_form(self, step):
        self.editor_form_loading = True
        try:
            self.step_action_var.set(step.get('action', ''))
            self._set_step_field_value('into', step.get('into', ''))
            self.step_json_text.delete('1.0', tk.END)
            self.step_json_text.insert('1.0', json.dumps(step, ensure_ascii=False, indent=2))
            field_values = {
                'image': step.get('image', ''),
                'similarity': '' if step.get('similarity') is None else str(step.get('similarity')),
                'color': 'true' if step.get('color') else 'false',
                'interrupt_if_not_found': 'true' if step.get('interrupt_if_not_found') else 'false',
                'region': step.get('region', ''),
                'seconds': '' if step.get('seconds') is None else str(step.get('seconds')),
                'flex': '' if step.get('flex') is None else str(step.get('flex')),
                'path': step.get('path', ''),
                'routine': step.get('routine', ''),
                'var': step.get('var', ''),
                'value': self._value_to_editor_text(step.get('value')),
                'amount': '' if step.get('amount') is None else str(step.get('amount')),
                'times': '' if step.get('times') is None else str(step.get('times')),
                'message': step.get('message', ''),
                'plugin': step.get('plugin', ''),
                'variables_json': self._value_to_editor_text(step.get('variables')) if 'variables' in step else '',
                'payload_json': self._value_to_editor_text(self._step_plugin_payload(step)),
                'method': step.get('method', ''),
                'oil_limit': self._value_to_editor_text(step.get('oil_limit')) if 'oil_limit' in step else '',
                'from_json': json.dumps(step.get('from', {}), ensure_ascii=False) if step.get('from') else '',
                'to_json': json.dumps(step.get('to', {}), ensure_ascii=False) if step.get('to') else '',
                'duration_ms': '' if step.get('duration_ms') is None else str(step.get('duration_ms')),
                'timeout': '' if step.get('timeout') is None else str(step.get('timeout')),
                'poll_seconds': '' if step.get('poll_seconds') is None else str(step.get('poll_seconds')),
                'into': step.get('into', ''),
            }
            for field_name, field_value in field_values.items():
                self._set_step_field_value(field_name, field_value)
            self.step_max_iterations_var.set('' if step.get('max_iterations') is None else str(step.get('max_iterations')))
        finally:
            self.editor_form_loading = False
        self._refresh_step_form_controls()

    def _populate_condition_form(self, condition):
        self.editor_form_loading = True
        try:
            self.condition_items = []
            self.condition_item_index = None
            self.condition_type_var.set(condition.get('type', ''))
            self.condition_field_vars['image'].set(condition.get('image', ''))
            self.condition_field_vars['similarity'].set('' if condition.get('similarity') is None else str(condition.get('similarity')))
            self.condition_field_vars['color'].set('true' if condition.get('color') else 'false')
            self.condition_field_vars['interrupt_if_not_found'].set('true' if condition.get('interrupt_if_not_found') else 'false')
            self.condition_field_vars['x_between'].set(self._value_to_editor_text(condition.get('x_between')) if 'x_between' in condition else '')
            self.condition_field_vars['y_between'].set(self._value_to_editor_text(condition.get('y_between')) if 'y_between' in condition else '')
            self.condition_field_vars['source'].set(condition.get('source', 'var'))
            self.condition_field_vars['key'].set(condition.get('key', ''))
            self.condition_field_vars['op'].set(condition.get('op', 'truthy'))
            self.condition_field_vars['value'].set(self._value_to_editor_text(condition.get('value')))
            self.condition_field_vars['region'].set(json.dumps(condition.get('region', {}), ensure_ascii=False) if condition.get('region') else '')
            self.condition_field_vars['channel'].set('' if condition.get('channel') is None else str(condition.get('channel')))
            match = condition.get('match') or {}
            self.condition_field_vars['match_low'].set(self._value_to_editor_text(match.get('low')) if 'low' in match else '')
            self.condition_field_vars['match_high'].set(self._value_to_editor_text(match.get('high')) if 'high' in match else '')
            self.condition_field_vars['plugin'].set(condition.get('plugin', ''))
            self.condition_field_vars['payload_json'].set(self._value_to_editor_text(self._condition_plugin_payload(condition)))
            if condition.get('type') in ('all', 'any'):
                self.condition_items = copy.deepcopy(condition.get('items', []))
            elif condition.get('type') == 'not' and condition.get('item') is not None:
                self.condition_items = [copy.deepcopy(condition.get('item'))]
            self._refresh_condition_items_list()
            if self.condition_items:
                self.condition_item_index = 0
                self.condition_items_list.selection_set(0)
                self._load_condition_item_into_fields(self.condition_items[0])
            self.condition_json_text.delete('1.0', tk.END)
            self.condition_json_text.insert('1.0', json.dumps(condition, ensure_ascii=False, indent=2))
        finally:
            self.editor_form_loading = False
        self._refresh_condition_form_controls()

    def _collect_step_form_value(self):
        raw = self.step_json_text.get('1.0', tk.END).strip() or '{}'
        step = json.loads(raw)
        action = self.step_action_var.get().strip()
        step['action'] = action
        for key in (
            'image', 'similarity', 'color', 'interrupt_if_not_found', 'region', 'seconds', 'flex',
            'path', 'routine', 'var', 'value', 'amount', 'times', 'message', 'plugin', 'variables',
            'method', 'oil_limit', 'from', 'to', 'duration_ms', 'max_iterations', 'timeout',
            'poll_seconds', 'into'
        ):
            step.pop(key, None)
        if action != 'plugin':
            for key in list(step.keys()):
                if key not in ('action', 'condition', 'steps', 'else_steps', 'timeout_steps'):
                    pass

        self._set_or_remove(step, 'into', self.step_field_vars['into'].get().strip())

        if action in ('tap_image', 'tap_found_image'):
            step['image'] = self.step_field_vars['image'].get().strip()
            self._set_or_remove(step, 'similarity', self._parse_optional_number(self.step_field_vars['similarity'].get().strip()))
            if self._bool_field_value(self.step_field_vars['color'].get()):
                step['color'] = True
            else:
                step.pop('color', None)
            if action == 'tap_found_image':
                if self._bool_field_value(self.step_field_vars['interrupt_if_not_found'].get()):
                    step['interrupt_if_not_found'] = True
                else:
                    step.pop('interrupt_if_not_found', None)
        elif action == 'tap_region':
            step['region'] = self.step_field_vars['region'].get().strip()
        elif action == 'sleep':
            step['seconds'] = self._parse_optional_number(self.step_field_vars['seconds'].get().strip(), default=1)
            self._set_or_remove(step, 'flex', self._parse_optional_number(self.step_field_vars['flex'].get().strip()))
        elif action == 'wait_update_screen':
            step['seconds'] = self._parse_optional_number(self.step_field_vars['seconds'].get().strip(), default=1)
        elif action == 'run_macro':
            step['path'] = self.step_field_vars['path'].get().strip()
            variables_raw = self.step_field_vars['variables_json'].get().strip()
            self._set_or_remove(step, 'variables', self._parse_json_object(variables_raw, default={}) if variables_raw else None)
        elif action == 'call':
            step['routine'] = self.step_field_vars['routine'].get().strip()
        elif action == 'set':
            step['var'] = self.step_field_vars['var'].get().strip()
            step['value'] = self._parse_loose_value(self.step_field_vars['value'].get().strip())
        elif action == 'increment':
            step['var'] = self.step_field_vars['var'].get().strip()
            step['amount'] = self._parse_optional_number(self.step_field_vars['amount'].get().strip(), default=1)
        elif action == 'repeat':
            step['times'] = int(self._parse_optional_number(self.step_field_vars['times'].get().strip(), default=1))
        elif action == 'return':
            step['value'] = self._parse_loose_value(self.step_field_vars['value'].get().strip())
        elif action == 'log':
            step['message'] = self.step_field_vars['message'].get()
        elif action in ('if', 'while', 'wait_for'):
            step['condition'] = self._collect_condition_form_value()
            if action == 'while':
                self._set_or_remove(step, 'max_iterations', self._parse_optional_number(self.step_max_iterations_var.get().strip()))
            elif action == 'wait_for':
                step['timeout'] = self._parse_optional_number(self.step_field_vars['timeout'].get().strip(), default=10)
                step['poll_seconds'] = self._parse_optional_number(self.step_field_vars['poll_seconds'].get().strip(), default=0.5)
        elif action == 'swipe':
            step['from'] = self._parse_json_object(self.step_field_vars['from_json'].get().strip(), default={})
            step['to'] = self._parse_json_object(self.step_field_vars['to_json'].get().strip(), default={})
            step['duration_ms'] = int(self._parse_optional_number(self.step_field_vars['duration_ms'].get().strip(), default=300))
        elif action == 'plugin':
            step['plugin'] = self.step_field_vars['plugin'].get().strip()
            payload = self._parse_json_object(self.step_field_vars['payload_json'].get().strip(), default={})
            for key, value in payload.items():
                step[key] = value
        elif action == 'stats_increment':
            step['method'] = self.step_field_vars['method'].get().strip()
        elif action == 'print_stats':
            oil_limit_raw = self.step_field_vars['oil_limit'].get().strip()
            if oil_limit_raw:
                step['oil_limit'] = self._parse_loose_value(oil_limit_raw)
        return normalize_macro({'steps': [step]})['steps'][0]

    def _collect_condition_form_value(self):
        raw = self.condition_json_text.get('1.0', tk.END).strip() or '{}'
        condition = json.loads(raw)
        condition_type = self.condition_type_var.get().strip()
        condition['type'] = condition_type
        if condition_type == 'image':
            condition['image'] = self.condition_field_vars['image'].get().strip()
            self._set_or_remove(condition, 'similarity', self._parse_optional_number(self.condition_field_vars['similarity'].get().strip()))
            if self._bool_field_value(self.condition_field_vars['color'].get()):
                condition['color'] = True
            else:
                condition.pop('color', None)
            if self._bool_field_value(self.condition_field_vars['interrupt_if_not_found'].get()):
                condition['interrupt_if_not_found'] = True
            else:
                condition.pop('interrupt_if_not_found', None)
            x_between = self.condition_field_vars['x_between'].get().strip()
            y_between = self.condition_field_vars['y_between'].get().strip()
            self._set_or_remove(condition, 'x_between', self._parse_loose_value(x_between) if x_between else None)
            self._set_or_remove(condition, 'y_between', self._parse_loose_value(y_between) if y_between else None)
        elif condition_type == 'compare':
            condition['source'] = self.condition_field_vars['source'].get().strip()
            condition['key'] = self.condition_field_vars['key'].get().strip()
            condition['op'] = self.condition_field_vars['op'].get().strip() or 'truthy'
            if condition['op'] == 'truthy':
                condition.pop('value', None)
            else:
                condition['value'] = self._parse_loose_value(self.condition_field_vars['value'].get().strip())
        elif condition_type == 'region_color':
            condition['region'] = self._parse_json_object(self.condition_field_vars['region'].get().strip(), default={})
            match_low = self.condition_field_vars['match_low'].get().strip()
            match_high = self.condition_field_vars['match_high'].get().strip()
            if match_low and match_high:
                condition['match'] = {
                    'low': self._parse_loose_value(match_low),
                    'high': self._parse_loose_value(match_high),
                }
                condition.pop('channel', None)
                condition.pop('op', None)
                condition.pop('value', None)
            else:
                condition.pop('match', None)
                condition['channel'] = int(self._parse_optional_number(self.condition_field_vars['channel'].get().strip(), default=0))
                condition['op'] = self.condition_field_vars['op'].get().strip() or 'gt'
                condition['value'] = self._parse_loose_value(self.condition_field_vars['value'].get().strip() or '0')
        elif condition_type == 'always':
            condition['value'] = True
        elif condition_type == 'plugin':
            condition['plugin'] = self.condition_field_vars['plugin'].get().strip()
            payload = self._parse_json_object(self.condition_field_vars['payload_json'].get().strip(), default={})
            for key, value in payload.items():
                condition[key] = value
        elif condition_type in ('all', 'any'):
            self._store_current_condition_item()
            condition['items'] = copy.deepcopy(self.condition_items)
            condition.pop('item', None)
        elif condition_type == 'not':
            self._store_current_condition_item()
            condition['item'] = copy.deepcopy(self.condition_items[0]) if self.condition_items else {'type': 'image', 'image': ''}
            condition.pop('items', None)
        return normalize_macro({'steps': [{'action': 'if', 'condition': condition, 'steps': []}]})['steps'][0]['condition']

    def _set_or_remove(self, obj, key, value):
        if value in ('', None):
            obj.pop(key, None)
        else:
            obj[key] = value

    def _on_step_action_changed(self, _event=None):
        self._refresh_step_form_controls()

    def _on_condition_type_changed(self, _event=None):
        self._refresh_condition_form_controls()

    def _step_form_config(self, action):
        configs = {
            'tap_image': {
                'visible_fields': ['image', 'similarity', 'color', 'into'],
                'hint': 'Choose a template image and optional similarity or color match.',
            },
            'tap_found_image': {
                'visible_fields': ['image', 'similarity', 'color', 'interrupt_if_not_found', 'into'],
                'hint': 'Find an image first, then tap the found region.',
            },
            'tap_region': {
                'visible_fields': ['region'],
                'hint': 'Choose one of the named regions in this macro.',
            },
            'sleep': {
                'visible_fields': ['seconds', 'flex'],
                'hint': 'Seconds is required. Flex is optional.',
            },
            'wait_update_screen': {
                'visible_fields': ['seconds'],
                'hint': 'Wait, then refresh the screen.',
            },
            'run_macro': {
                'visible_fields': ['path', 'variables_json', 'into'],
                'hint': 'Run another macro file and optionally pass variables.',
            },
            'call': {
                'visible_fields': ['routine', 'into'],
                'hint': 'Call a routine defined in this macro.',
            },
            'set': {
                'visible_fields': ['var', 'value'],
                'hint': 'Set a variable to a literal or ref object.',
            },
            'increment': {
                'visible_fields': ['var', 'amount'],
                'hint': 'Increment a variable by an amount.',
            },
            'repeat': {
                'visible_fields': ['times'],
                'hint': 'Repeat child steps a fixed number of times.',
            },
            'return': {
                'visible_fields': ['value'],
                'hint': 'Return a literal or ref object.',
            },
            'log': {
                'visible_fields': ['message'],
                'hint': 'Messages support {{var}} placeholders.',
            },
            'while': {
                'visible_fields': [],
                'hint': 'Loop while the condition is true. Max iterations is optional.',
            },
            'wait_for': {
                'visible_fields': ['timeout', 'poll_seconds', 'into'],
                'hint': 'Poll until the condition passes or the timeout expires.',
            },
            'swipe': {
                'visible_fields': ['from_json', 'to_json', 'duration_ms'],
                'hint': 'Use JSON points like {"x":960,"y":680}.',
            },
            'plugin': {
                'visible_fields': ['plugin', 'payload_json', 'into'],
                'hint': 'Plugin payload is any extra JSON object passed to the plugin.',
            },
            'stats_increment': {
                'visible_fields': ['method'],
                'hint': 'Choose the stats increment method to call.',
            },
            'print_stats': {
                'visible_fields': ['oil_limit'],
                'hint': 'Oil limit can be a number or a ref object.',
            },
            'if': {
                'visible_fields': [],
                'hint': 'This action has no direct fields besides the condition or child steps.',
            },
            'update_screen': {
                'visible_fields': [],
                'hint': 'This action has no direct fields besides the condition or child steps.',
            },
            'back': {
                'visible_fields': [],
                'hint': 'This action has no direct fields besides the condition or child steps.',
            },
            'continue': {
                'visible_fields': [],
                'hint': 'This action has no direct fields besides the condition or child steps.',
            },
            'break': {
                'visible_fields': [],
                'hint': 'This action has no direct fields besides the condition or child steps.',
            },
        }
        return configs.get(action, {'visible_fields': [], 'hint': 'Edit the selected step.'})

    def _condition_form_config(self, condition_type):
        configs = {
            'image': {
                'visible_fields': ['image', 'similarity', 'color', 'interrupt_if_not_found', 'x_between', 'y_between'],
                'hint': 'Pick an image template and optional match constraints.',
            },
            'compare': {
                'visible_fields': ['source', 'key', 'op', 'value'],
                'hint': 'Compare runtime data or a variable.',
            },
            'region_color': {
                'visible_fields': ['region', 'channel', 'op', 'value', 'match_low', 'match_high'],
                'hint': 'Use channel/op/value or low/high match bounds.',
            },
            'plugin': {
                'visible_fields': ['plugin', 'payload_json'],
                'hint': 'Plugin conditions receive an extra payload JSON object.',
            },
            'all': {
                'visible_fields': [],
                'hint': 'Composite conditions can be edited in the child list below.',
            },
            'any': {
                'visible_fields': [],
                'hint': 'Composite conditions can be edited in the child list below.',
            },
            'not': {
                'visible_fields': [],
                'hint': 'Composite conditions can be edited in the child list below.',
            },
            'always': {
                'visible_fields': [],
                'hint': 'Always true. No extra fields are needed.',
            },
        }
        return configs.get(condition_type, {'visible_fields': [], 'hint': 'Edit the selected condition.'})

    def _refresh_step_form_controls(self):
        action = self.step_action_var.get().strip()
        regions = self._current_region_names()
        routines = self._current_routine_names()
        config = self._step_form_config(action)
        visible_fields = config['visible_fields']
        hint = config['hint']
        field_values = {
            'image': self.asset_keys,
            'similarity': ['0.7', '0.8', '0.9', '0.95', '0.99'],
            'color': ['false', 'true'],
            'interrupt_if_not_found': ['false', 'true'],
            'region': regions,
            'path': self.available_macro_files,
            'routine': routines,
            'var': self._current_variable_names(),
            'method': [name for name in dir(Stats(None)) if name.startswith('increment_')],
        }
        readonly_fields = {'color', 'interrupt_if_not_found'}

        self._set_field_visibility(self.step_field_rows, visible_fields)
        self._set_section_visibility(self.step_fields_frame, bool(visible_fields), fill='x', pady=(8, 0))
        for field_name, widget in self.step_field_widgets.items():
            values = field_values.get(field_name, [])
            if isinstance(widget, ttk.Combobox):
                widget.configure(values=values)
            state = 'readonly' if field_name in readonly_fields or field_name in ('image', 'region', 'path', 'routine', 'method') and values else 'normal'
            widget.configure(state=state)
        if hasattr(self, 'add_step_image_button'):
            if action in ('tap_image', 'tap_found_image'):
                if not self.step_image_button_row.winfo_ismapped():
                    self.step_image_button_row.pack(fill='x', pady=(8, 0), before=self.step_advanced_toggle)
                self.add_step_image_button.configure(state='normal')
            else:
                self.step_image_button_row.pack_forget()
                self.add_step_image_button.configure(state='disabled')
        if hasattr(self, 'pick_step_image_button'):
            allow_image_pick = action in ('tap_image', 'tap_found_image') and bool(self.step_field_vars['image'].get().strip())
            self.pick_step_image_button.configure(state='normal' if allow_image_pick else 'disabled')
        if action == 'while':
            if not self.step_loop_frame.winfo_ismapped():
                self.step_loop_frame.pack(fill='x', pady=(8, 0), before=self.step_advanced_toggle)
        else:
            self.step_loop_frame.pack_forget()
        self.step_form_hint_var.set(hint)

    def _refresh_condition_form_controls(self):
        condition_type = self.condition_type_var.get().strip()
        config = self._condition_form_config(condition_type)
        composite_visible = condition_type in ('all', 'any', 'not')
        visible_fields = config['visible_fields']
        hint = config['hint']

        self._set_field_visibility(self.condition_field_rows, visible_fields)
        self._set_section_visibility(self.condition_fields_frame, bool(visible_fields), fill='x', pady=(8, 0))
        self.condition_image_input.configure(values=self.asset_keys, state='readonly' if 'image' in visible_fields else 'disabled')
        self.condition_source_combo.configure(values=['var', 'runtime'], state='readonly' if 'source' in visible_fields else 'disabled')
        key_values = []
        if condition_type == 'compare':
            source = self.condition_field_vars['source'].get().strip() or 'var'
            if source == 'var':
                key_values = self._current_variable_names()
            elif source == 'runtime':
                key_values = self._current_runtime_keys()
        self.condition_key_combo.configure(values=key_values, state='readonly' if 'key' in visible_fields and key_values else ('normal' if 'key' in visible_fields else 'disabled'))
        self.condition_op_combo.configure(values=['truthy', 'equals', 'not_equals', 'gt', 'gte', 'lt', 'lte'], state='readonly' if 'op' in visible_fields else 'disabled')
        if 'color' in visible_fields:
            self.condition_field_widgets['color'].configure(values=['false', 'true'], state='readonly')
        if 'interrupt_if_not_found' in visible_fields:
            self.condition_field_widgets['interrupt_if_not_found'].configure(values=['false', 'true'], state='readonly')
        if 'similarity' in visible_fields:
            self.condition_field_widgets['similarity'].configure(values=['0.7', '0.8', '0.9', '0.95', '0.99'])
        if hasattr(self, 'add_condition_image_button'):
            if 'image' in visible_fields:
                if not self.condition_image_button_row.winfo_ismapped():
                    self.condition_image_button_row.pack(fill='x', pady=(8, 0), before=self.condition_advanced_toggle)
                self.add_condition_image_button.configure(state='normal')
            else:
                self.condition_image_button_row.pack_forget()
                self.add_condition_image_button.configure(state='disabled')
        if hasattr(self, 'pick_condition_image_button'):
            allow_image_pick = bool(self._current_condition_editor_image_key())
            self.pick_condition_image_button.configure(state='normal' if allow_image_pick else 'disabled')
        if composite_visible:
            if not self.condition_items_frame.winfo_ismapped():
                self.condition_items_frame.pack(fill='x', pady=(8, 0), before=self.condition_advanced_toggle)
        else:
            self.condition_items_frame.pack_forget()
        self.condition_form_hint_var.set(hint)

    def _refresh_condition_items_list(self):
        self.condition_items_list.delete(0, tk.END)
        for index, item in enumerate(self.condition_items):
            self.condition_items_list.insert(tk.END, '[{}] {}'.format(index, self._describe_condition(item)))
        if self.condition_item_index is not None and 0 <= self.condition_item_index < len(self.condition_items):
            self.condition_items_list.selection_clear(0, tk.END)
            self.condition_items_list.selection_set(self.condition_item_index)

    def _on_condition_item_select(self, _event=None):
        selection = self.condition_items_list.curselection()
        if not selection:
            self.condition_item_index = None
            self._refresh_editor_image_preview()
            return
        self._store_current_condition_item()
        self.condition_item_index = selection[0]
        self._load_condition_item_into_fields(self.condition_items[self.condition_item_index])
        self._refresh_editor_image_preview()

    def _load_condition_item_into_fields(self, condition):
        target = condition.get('item') if condition.get('type') == 'not' and isinstance(condition.get('item'), dict) else condition
        self.condition_field_vars['image'].set(target.get('image', ''))
        self.condition_field_vars['source'].set(target.get('source', 'var'))
        self.condition_field_vars['key'].set(target.get('key', ''))
        self.condition_field_vars['op'].set(target.get('op', 'truthy'))
        self.condition_field_vars['value'].set(self._value_to_editor_text(target.get('value')))
        self.condition_field_vars['region'].set(json.dumps(target.get('region', {}), ensure_ascii=False) if target.get('region') else '')

    def _store_current_condition_item(self):
        condition_type = self.condition_type_var.get().strip()
        if condition_type not in ('all', 'any', 'not'):
            return
        if self.condition_item_index is None or not (0 <= self.condition_item_index < len(self.condition_items)):
            return
        item = self.condition_items[self.condition_item_index]
        target = item.get('item') if item.get('type') == 'not' and isinstance(item.get('item'), dict) else item
        item_type = target.get('type')
        if item_type == 'image':
            target['image'] = self.condition_field_vars['image'].get().strip()
        elif item_type == 'compare':
            target['source'] = self.condition_field_vars['source'].get().strip()
            target['key'] = self.condition_field_vars['key'].get().strip()
            target['op'] = self.condition_field_vars['op'].get().strip() or 'truthy'
            if target['op'] == 'truthy':
                target.pop('value', None)
            else:
                target['value'] = self._parse_loose_value(self.condition_field_vars['value'].get().strip())
        elif item_type == 'region_color':
            target['region'] = self._parse_json_object(self.condition_field_vars['region'].get().strip(), default={})
        self._refresh_condition_items_list()
        self._refresh_editor_image_preview()

    def _add_condition_item(self, item_type):
        self._store_current_condition_item()
        if item_type == 'image':
            item = {'type': 'image', 'image': ''}
        elif item_type == 'compare':
            item = {'type': 'compare', 'source': 'var', 'key': '', 'op': 'truthy'}
        elif item_type == 'region_color':
            item = {'type': 'region_color', 'region': {'x': 0, 'y': 0, 'w': 1, 'h': 1}, 'channel': 0, 'op': 'gt', 'value': 0}
        else:
            item = {'type': 'not', 'item': {'type': 'image', 'image': ''}}
        if self.condition_type_var.get().strip() == 'not':
            self.condition_items = [item]
            self.condition_item_index = 0
        else:
            self.condition_items.append(item)
            self.condition_item_index = len(self.condition_items) - 1
        self._refresh_condition_items_list()
        self._load_condition_item_into_fields(item if item_type != 'not' else item['item'])
        self._refresh_editor_image_preview()

    def _remove_condition_item(self):
        selection = self.condition_items_list.curselection()
        if not selection:
            return
        index = selection[0]
        self.condition_items.pop(index)
        if not self.condition_items:
            self.condition_item_index = None
            self.condition_field_vars['image'].set('')
            self.condition_field_vars['key'].set('')
            self.condition_field_vars['value'].set('')
        else:
            self.condition_item_index = min(index, len(self.condition_items) - 1)
            self._load_condition_item_into_fields(self.condition_items[self.condition_item_index])
        self._refresh_condition_items_list()
        self._refresh_editor_image_preview()

    def _set_step_field_value(self, field_name, value):
        self.step_field_vars[field_name].set('' if value is None else str(value))

    def _set_field_visibility(self, row_map, visible_fields):
        visible = set(visible_fields)
        for field_name, row in row_map.items():
            if field_name in visible:
                if row.winfo_manager() != 'pack':
                    row.pack(fill='x', pady=(0, 8))
            else:
                row.pack_forget()

    def _set_section_visibility(self, section, visible, **pack_kwargs):
        if visible:
            if section.winfo_manager() != 'pack':
                section.pack(**pack_kwargs)
        else:
            section.pack_forget()

    def _bool_field_value(self, raw):
        return bool(self._parse_loose_value(raw)) if raw not in ('', None) else False

    def _step_plugin_payload(self, step):
        payload = dict(step)
        for key in (
            'action', 'plugin', 'into', 'steps', 'else_steps', 'timeout_steps', 'condition'
        ):
            payload.pop(key, None)
        return payload

    def _condition_plugin_payload(self, condition):
        payload = dict(condition)
        for key in ('type', 'plugin', 'items', 'item'):
            payload.pop(key, None)
        return payload

    def _current_region_names(self):
        if not isinstance(self.editor_data, dict):
            return []
        return sorted((self.editor_data.get('regions') or {}).keys())

    def _current_routine_names(self):
        if not isinstance(self.editor_data, dict):
            return []
        return sorted((self.editor_data.get('routines') or {}).keys())

    def _current_variable_names(self):
        names = set()

        def visit_steps(steps):
            for step in steps or []:
                if not isinstance(step, dict):
                    continue
                if step.get('action') in ('set', 'increment') and step.get('var'):
                    names.add(step['var'])
                visit_steps(step.get('steps'))
                visit_steps(step.get('else_steps'))
                visit_steps(step.get('timeout_steps'))

        if isinstance(self.editor_data, dict):
            visit_steps(self.editor_data.get('steps'))
            for routine_steps in (self.editor_data.get('routines') or {}).values():
                visit_steps(routine_steps)
        return sorted(names)

    def _on_editor_image_field_changed(self, *_args):
        if not hasattr(self, 'editor_template_label'):
            return
        if getattr(self, 'editor_form_loading', False):
            return
        if hasattr(self, 'step_action_var'):
            self._refresh_step_form_controls()
        if hasattr(self, 'condition_type_var'):
            self._refresh_condition_form_controls()
        self._refresh_editor_image_preview()

    def _refresh_editor_image_preview(self, path_parts=None, value=None):
        selection = self.structure.selection()
        current_path = path_parts
        current_value = value
        if current_path is None or current_value is None:
            if not selection or self.editor_data is None:
                self._set_editor_image_preview(None)
                return
            item = selection[0]
            current_path = self.tree_paths.get(item, [])
            current_value = self._get_by_path(current_path)

        image_key = self._extract_editor_image_key(current_path, current_value)
        form_mode = self.editor_form_mode_var.get()
        if not image_key and form_mode == 'Form: step':
            action = self.step_action_var.get().strip()
            if action in ('tap_image', 'tap_found_image'):
                image_key = self.step_field_vars['image'].get().strip()
        if not image_key and form_mode in ('Form: condition', 'Form: step + condition'):
            image_key = self._current_condition_editor_image_key()
        self._set_editor_image_preview(image_key)

    def _extract_editor_image_key(self, path_parts, value):
        if isinstance(value, dict):
            if value.get('action') in ('tap_image', 'tap_found_image'):
                return value.get('image') or None
            nested = self._extract_image_from_condition(value)
            if nested:
                return nested
        if path_parts and path_parts[-1] == 'image' and isinstance(value, str):
            return value.strip() or None
        return None

    def _current_condition_editor_image_key(self):
        condition_type = self.condition_type_var.get().strip()
        if condition_type == 'image':
            return self.condition_field_vars['image'].get().strip()
        if condition_type in ('all', 'any', 'not'):
            if self.condition_item_index is not None and 0 <= self.condition_item_index < len(self.condition_items):
                return self._extract_image_from_condition(self.condition_items[self.condition_item_index])
            if self.condition_items:
                return self._extract_image_from_condition(self.condition_items[0])
        return None

    def _current_editor_image_capture_key(self):
        form_mode = self.editor_form_mode_var.get()
        if form_mode == 'Form: step':
            action = self.step_action_var.get().strip()
            if action in ('tap_image', 'tap_found_image'):
                return self.step_field_vars['image'].get().strip() or None
        if form_mode in ('Form: condition', 'Form: step + condition'):
            image_key = self._current_condition_editor_image_key()
            if image_key:
                return image_key
        selection = self.structure.selection()
        if selection and self.editor_data is not None:
            path_parts = self.tree_paths.get(selection[0], [])
            value = self._get_by_path(path_parts)
            return self._extract_editor_image_key(path_parts, value)
        return None

    def _current_editor_image_field_value(self, target):
        if target == 'step':
            return self.step_field_vars['image'].get().strip()
        return self.condition_field_vars['image'].get().strip()

    def _set_editor_image_field_value(self, target, image_key):
        if target == 'step':
            self.step_field_vars['image'].set(image_key)
            self._refresh_step_form_controls()
        else:
            self.condition_field_vars['image'].set(image_key)
            self._refresh_condition_form_controls()
        self._set_editor_image_preview(image_key)
        self._set_current_image(image_key)

    def _start_new_image_pick(self, target):
        if self.last_frame is None:
            self.editor_status_var.set('Refresh Preview first')
            return
        current_value = self._current_editor_image_field_value(target)
        suggested_key = current_value or 'new/image'
        image_key = simpledialog.askstring('Image Key', 'Asset key (relative path, no extension):', initialvalue=suggested_key, parent=self.root)
        if image_key is None:
            self.editor_status_var.set('Add image cancelled')
            return
        normalized_key = image_key.strip().replace('\\', '/').strip('/')
        if not normalized_key:
            self.editor_status_var.set('Image key is required')
            return
        self._set_editor_image_field_value(target, normalized_key)
        self.preview_pick_mode = 'image'
        self.region_pick_path = None
        self.region_pick_active = True
        self.canvas_drag_start = None
        if self.canvas_drag_rect_id is not None:
            self.canvas.delete(self.canvas_drag_rect_id)
            self.canvas_drag_rect_id = None
        self.editor_status_var.set('Drag on preview to capture {}'.format(normalized_key))
        self._show_canvas_crosshair(True)

    def _extract_image_from_condition(self, condition):
        if not isinstance(condition, dict):
            return None
        condition_type = condition.get('type')
        if condition_type == 'image':
            image_key = condition.get('image')
            return image_key.strip() if isinstance(image_key, str) and image_key.strip() else None
        if condition_type == 'not':
            return self._extract_image_from_condition(condition.get('item'))
        if condition_type in ('all', 'any'):
            for item in condition.get('items') or []:
                image_key = self._extract_image_from_condition(item)
                if image_key:
                    return image_key
        return None

    def _save_image_from_preview_region(self, region):
        image_key = self._current_editor_image_capture_key()
        if not image_key:
            self.editor_status_var.set('No image key selected for capture')
            return
        if self.last_frame is None:
            self.editor_status_var.set('Refresh Preview first')
            return
        x = max(0, int(region['x']))
        y = max(0, int(region['y']))
        w = max(1, int(region['w']))
        h = max(1, int(region['h']))
        frame_h, frame_w = self.last_frame.shape[:2]
        x2 = min(frame_w, x + w)
        y2 = min(frame_h, y + h)
        if x >= x2 or y >= y2:
            self.editor_status_var.set('Selected image area is empty')
            return
        cropped = self.last_frame[y:y2, x:x2].copy()
        asset_path = os.path.join(os.getcwd(), 'assets', self.config.assets['server'], image_key + '.png')
        if os.path.exists(asset_path):
            overwrite = messagebox.askyesno('Overwrite Image', 'Asset already exists. Overwrite it?', parent=self.root)
            if not overwrite:
                self.editor_status_var.set('Image capture cancelled')
                return
        os.makedirs(os.path.dirname(asset_path), exist_ok=True)
        encoded, buffer = cv2.imencode('.png', cropped)
        if not encoded:
            self.editor_status_var.set('Failed to encode preview crop')
            return
        buffer.tofile(asset_path)
        self.asset_keys = self._load_asset_keys()
        self._refresh_step_form_controls()
        self._refresh_condition_form_controls()
        self._set_editor_image_preview(image_key)
        self._set_current_image(image_key)
        self.editor_status_var.set('Saved preview crop to {}'.format(image_key))

    def _set_editor_image_preview(self, image_key):
        normalized = image_key.strip() if isinstance(image_key, str) else ''
        if not normalized:
            self.editor_image_var.set('image: -')
            self.editor_template_label.configure(image='', text='No image')
            self.editor_template_label.image = None
            self.editor_template_photo = None
            return
        self.editor_image_var.set('image: {}'.format(normalized))
        self._render_image_preview(normalized, self.editor_template_label, 'editor_template_photo')

    def _load_asset_keys(self):
        asset_root = os.path.join(os.getcwd(), 'assets', self.config.assets['server'])
        keys = []
        if not os.path.isdir(asset_root):
            return keys
        for root, _, files in os.walk(asset_root):
            for name in files:
                if not name.lower().endswith('.png'):
                    continue
                full_path = os.path.join(root, name)
                rel_path = os.path.relpath(full_path, asset_root)
                keys.append(os.path.splitext(rel_path)[0].replace('\\', '/'))
        return sorted(keys)

    def _list_macro_files(self):
        macro_dir = os.path.join(os.getcwd(), 'macros')
        if not os.path.isdir(macro_dir):
            return []
        names = []
        for name in os.listdir(macro_dir):
            if not name.lower().endswith('.json'):
                continue
            if name in ('default_manifest.json',):
                continue
            names.append(name)
        return sorted(names)

    def _parse_optional_number(self, raw, default=None):
        if raw in ('', None):
            return default
        return float(raw) if '.' in str(raw) else int(raw)

    def _parse_loose_value(self, raw):
        if raw in ('', None):
            return ''
        lower = str(raw).strip().lower()
        if lower == 'true':
            return True
        if lower == 'false':
            return False
        if lower == 'null':
            return None
        try:
            return json.loads(raw)
        except Exception:
            return raw

    def _parse_json_object(self, raw, default=None):
        if not raw:
            return {} if default is None else default
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('Expected JSON object.')
        return value

    def _value_to_editor_text(self, value):
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if value is True:
            return 'true'
        if value is False:
            return 'false'
        if value is None:
            return 'null'
        return '' if value == '' else str(value)

    def _parse_value_from_form(self, value_type, raw):
        if value_type == 'string':
            return raw
        if value_type == 'number':
            return float(raw) if '.' in raw else int(raw)
        if value_type == 'bool':
            return raw.strip().lower() in ('true', '1', 'yes', 'y')
        if value_type == 'null':
            return None
        return json.loads(raw)

    def _list_item_label(self, index, child):
        if isinstance(child, dict):
            if 'action' in child:
                return '[{}] {}'.format(index, self._describe_step(child))
            if child.get('type'):
                return '[{}] {}'.format(index, self._describe_condition(child))
        return '[{}] {}'.format(index, self._scalar_text(child))

    def _describe_tree_node(self, label, value, path_parts):
        if isinstance(label, int):
            return self._list_item_label(label, value), self._node_value_summary(value)
        if path_parts == []:
            return 'Macro Root', self.editor_data.get('name', 'macro') if isinstance(self.editor_data, dict) else 'macro'
        if label == 'steps' and isinstance(value, list):
            return 'Steps', '{} items'.format(len(value))
        if label == 'routines' and isinstance(value, dict):
            return 'Routines', '{} routines'.format(len(value))
        if label == 'regions' and isinstance(value, dict):
            return 'Regions', '{} regions'.format(len(value))
        if path_parts[:1] == ['routines'] and len(path_parts) == 2 and isinstance(value, list):
            return 'Routine: {}'.format(label), '{} steps'.format(len(value))
        if path_parts[:1] == ['regions'] and len(path_parts) == 2 and isinstance(value, dict):
            return 'Region: {}'.format(label), self._format_region_preview(value)
        if label == 'condition' and isinstance(value, dict):
            return 'Condition', self._describe_condition(value)
        if label == 'else_steps' and isinstance(value, list):
            return 'Else Steps', '{} items'.format(len(value))
        if label == 'timeout_steps' and isinstance(value, list):
            return 'Timeout Steps', '{} items'.format(len(value))
        if isinstance(value, dict) and 'action' in value:
            return label, self._describe_step(value)
        if isinstance(value, dict) and value.get('type'):
            return label, self._describe_condition(value)
        if isinstance(value, dict) and value.get('ref'):
            return label, '{}:{}'.format(value.get('ref'), value.get('key'))
        if isinstance(value, list):
            return str(label), '{} items'.format(len(value))
        if isinstance(value, dict):
            return str(label), '{} fields'.format(len(value))
        return str(label), self._scalar_text(value)

    def _node_value_summary(self, value):
        if isinstance(value, list):
            return '{} items'.format(len(value))
        if isinstance(value, dict):
            if 'action' in value:
                return self._describe_step(value)
            if value.get('type'):
                return self._describe_condition(value)
            return '{} fields'.format(len(value))
        return self._scalar_text(value)

    def _describe_step(self, step):
        action = step.get('action', '?')
        if action == 'tap_image':
            return 'Tap image {}'.format(step.get('image', '-'))
        if action == 'tap_found_image':
            return 'Tap found image {}'.format(step.get('image', '-'))
        if action == 'tap_region':
            return 'Tap region {}'.format(step.get('region', '-'))
        if action == 'sleep':
            return 'Sleep {}s'.format(step.get('seconds', 0))
        if action == 'wait_update_screen':
            return 'Wait+Update {}s'.format(step.get('seconds', 0))
        if action == 'update_screen':
            return 'Update screen'
        if action == 'if':
            return 'If {}'.format(self._describe_condition(step.get('condition', {})))
        if action == 'while':
            return 'While {}'.format(self._describe_condition(step.get('condition', {})))
        if action == 'repeat':
            return 'Repeat {} times'.format(step.get('times', 1))
        if action == 'wait_for':
            return 'Wait for {}'.format(self._describe_condition(step.get('condition', {})))
        if action == 'run_macro':
            return 'Run macro {}'.format(step.get('path', '-'))
        if action == 'call':
            return 'Call routine {}'.format(step.get('routine', '-'))
        if action == 'set':
            return 'Set {} = {}'.format(step.get('var', '-'), self._value_ref_text(step.get('value')))
        if action == 'increment':
            return 'Increment {} by {}'.format(step.get('var', '-'), step.get('amount', 1))
        if action == 'swipe':
            start = step.get('from', {})
            end = step.get('to', {})
            return 'Swipe ({}, {}) -> ({}, {})'.format(start.get('x', '?'), start.get('y', '?'), end.get('x', '?'), end.get('y', '?'))
        if action == 'back':
            return 'Press back'
        if action == 'continue':
            return 'Continue loop'
        if action == 'break':
            return 'Break loop'
        if action == 'return':
            return 'Return {}'.format(self._value_ref_text(step.get('value')))
        if action == 'log':
            return 'Log: {}'.format(step.get('message', ''))
        if action == 'stats_increment':
            return 'Stats {}'.format(step.get('method', '-'))
        if action == 'print_stats':
            return 'Print stats'
        return action

    def _describe_condition(self, condition):
        if not isinstance(condition, dict):
            return self._scalar_text(condition)
        condition_type = condition.get('type')
        if condition_type == 'always':
            return 'always'
        if condition_type == 'image':
            return 'image {}'.format(condition.get('image', '-'))
        if condition_type == 'not':
            return 'not ({})'.format(self._describe_condition(condition.get('item')))
        if condition_type in ('all', 'any'):
            items = condition.get('items', [])
            joiner = ' and ' if condition_type == 'all' else ' or '
            parts = [self._describe_condition(item) for item in items[:3]]
            text = joiner.join(parts)
            if len(items) > 3:
                text += ' ...'
            return text or condition_type
        if condition_type == 'compare':
            op = condition.get('op', 'truthy')
            left = '{}:{}'.format(condition.get('source', '?'), condition.get('key', '?'))
            if op == 'truthy':
                return left
            return '{} {} {}'.format(left, op, self._value_ref_text(condition.get('value')))
        if condition_type == 'region_color':
            region = self._format_region_preview(condition.get('region', {}))
            match = condition.get('match')
            if match:
                return 'color {} in range'.format(region)
            return 'color {} {} {}'.format(region, condition.get('op', 'gt'), condition.get('value'))
        return condition_type or 'condition'

    def _format_region_preview(self, region):
        if not isinstance(region, dict):
            return self._scalar_text(region)
        return '({}, {}, {}, {})'.format(region.get('x', '?'), region.get('y', '?'), region.get('w', '?'), region.get('h', '?'))

    def _value_ref_text(self, value):
        if isinstance(value, dict) and value.get('ref'):
            return '{}:{}'.format(value.get('ref'), value.get('key'))
        return self._scalar_text(value)

    def _scalar_text(self, value):
        if isinstance(value, str):
            return value
        if value is True:
            return 'true'
        if value is False:
            return 'false'
        if value is None:
            return 'null'
        return str(value)

    def _infer_type_name(self, value):
        if isinstance(value, str):
            return 'string'
        if isinstance(value, bool):
            return 'bool'
        if isinstance(value, (int, float)):
            return 'number'
        if value is None:
            return 'null'
        return 'json'

    def _build_step_template(self, template_name):
        templates = {
            'log': {'action': 'log', 'message': 'message'},
            'tap_image': {'action': 'tap_image', 'image': 'menu/confirm'},
            'tap_found_image': {'action': 'tap_found_image', 'image': 'menu/confirm', 'into': 'found_image'},
            'tap_region': {'action': 'tap_region', 'region': 'hq_tab'},
            'sleep': {'action': 'sleep', 'seconds': 1},
            'wait_update_screen': {'action': 'wait_update_screen', 'seconds': 1},
            'update_screen': {'action': 'update_screen'},
            'if_image': {'action': 'if', 'condition': {'type': 'image', 'image': 'menu/confirm'}, 'steps': []},
            'if_not_battle': {'action': 'if', 'condition': {'type': 'not', 'item': {'type': 'image', 'image': 'menu/button_battle'}}, 'steps': [{'action': 'back'}]},
            'while_true': {'action': 'while', 'condition': {'type': 'always', 'value': True}, 'steps': []},
            'wait_for_image': {'action': 'wait_for', 'condition': {'type': 'image', 'image': 'menu/confirm'}, 'timeout': 10, 'poll_seconds': 0.5},
            'repeat': {'action': 'repeat', 'times': 3, 'steps': []},
            'run_macro': {'action': 'run_macro', 'path': 'mission_claim.json'},
            'plugin': {'action': 'plugin', 'plugin': 'headquarters.refill_dorm'},
            'set': {'action': 'set', 'var': 'value_name', 'value': 0},
            'increment': {'action': 'increment', 'var': 'counter', 'amount': 1},
            'stats_increment': {'action': 'stats_increment', 'name': 'counter', 'amount': 1},
            'print_stats': {'action': 'print_stats'},
            'return': {'action': 'return', 'value': True},
            'swipe': {'action': 'swipe', 'from': {'x': 960, 'y': 680}, 'to': {'x': 960, 'y': 320}, 'duration_ms': 300},
            'back': {'action': 'back'},
            'continue': {'action': 'continue'},
            'break': {'action': 'break'},
            'call_routine': {'action': 'call', 'routine': 'routine_name'}
        }
        return copy.deepcopy(templates[template_name])

    def _select_tree_path(self, path_parts):
        for item_id, item_path in self.tree_paths.items():
            if item_path == path_parts:
                self._open_tree_ancestors(path_parts)
                self.structure.selection_set(item_id)
                self.structure.focus(item_id)
                self.structure.see(item_id)
                self._on_tree_select()
                break

    def _select_tree_paths(self, path_list):
        item_ids = []
        for path_parts in path_list:
            self._open_tree_ancestors(path_parts)
            for item_id, item_path in self.tree_paths.items():
                if item_path == path_parts:
                    item_ids.append(item_id)
                    break
        if not item_ids:
            return
        self.structure.selection_set(item_ids)
        self.structure.focus(item_ids[0])
        self.structure.see(item_ids[0])
        self._on_tree_select()

    def _open_tree_ancestors(self, path_parts):
        for item_id, item_path in self.tree_paths.items():
            if len(item_path) <= len(path_parts) and item_path == path_parts[:len(item_path)]:
                self.structure.item(item_id, open=True)

    def _selected_tree_paths(self):
        paths = []
        for item_id in self.structure.selection():
            path_parts = self.tree_paths.get(item_id)
            if path_parts is not None:
                paths.append(list(path_parts))
        return paths

    def _get_selected_list_item_info(self):
        selected_paths = self._selected_tree_paths()
        if not selected_paths:
            return None
        normalized_paths = []
        parent_path = None
        for path_parts in selected_paths:
            if not path_parts or not isinstance(path_parts[-1], int):
                return None
            parent_info = self._get_parent_info(path_parts)
            if not parent_info or parent_info[1] != 'list':
                return None
            current_parent_path = path_parts[:-1]
            if parent_path is None:
                parent_path = current_parent_path
            elif current_parent_path != parent_path:
                return None
            normalized_paths.append(list(path_parts))
        normalized_paths.sort(key=lambda path: path[-1])
        return {
            'parent': self._get_by_path(parent_path) if parent_path else self.editor_data,
            'parent_path': list(parent_path),
            'paths': normalized_paths,
            'indices': [path[-1] for path in normalized_paths],
        }

    def _delete_multiple_selected_nodes(self):
        selection_info = self._get_selected_list_item_info()
        if not selection_info:
            self.editor_status_var.set('Multi-delete works for items from the same list')
            return False
        parent = selection_info['parent']
        indices = selection_info['indices']
        for index in reversed(indices):
            parent.pop(index)
        self.editor_status_var.set('Deleted {} nodes'.format(len(indices)))
        self._refresh_editor_structure()
        self._select_tree_path(selection_info['parent_path'])
        return True

    def _copy_selected_nodes(self, _event=None):
        selection_info = self._get_selected_list_item_info()
        if not selection_info:
            self.editor_status_var.set('Copy works for list items from the same list')
            return 'break'
        parent = selection_info['parent']
        self.editor_clipboard_nodes = [copy.deepcopy(parent[index]) for index in selection_info['indices']]
        self.editor_status_var.set('Copied {} node{}'.format(len(self.editor_clipboard_nodes), '' if len(self.editor_clipboard_nodes) == 1 else 's'))
        return 'break'

    def _paste_selected_nodes(self, _event=None):
        if not self.editor_clipboard_nodes:
            self.editor_status_var.set('Clipboard is empty')
            return 'break'
        selection = self.structure.selection()
        if self.editor_data is None:
            return 'break'
        if not selection:
            path_parts = []
            target = self.editor_data
        else:
            path_parts = self.tree_paths.get(selection[0], [])
            target = self._get_by_path(path_parts)
        if isinstance(target, list):
            target_list = target
            insert_at = len(target_list)
            parent_path = list(path_parts)
        else:
            parent_info = self._get_parent_info(path_parts)
            if not parent_info or parent_info[1] != 'list':
                self.editor_status_var.set('Paste works on a list or list item selection')
                return 'break'
            target_list = parent_info[0]
            insert_at = path_parts[-1] + 1
            parent_path = path_parts[:-1]
        new_paths = []
        for offset, node in enumerate(self.editor_clipboard_nodes):
            target_list.insert(insert_at + offset, copy.deepcopy(node))
            new_paths.append(parent_path + [insert_at + offset])
        self.editor_status_var.set('Pasted {} node{}'.format(len(new_paths), '' if len(new_paths) == 1 else 's'))
        self._refresh_editor_structure()
        self._select_tree_paths(new_paths)
        return 'break'

    def _move_list_items_to_index(self, selection_info, insert_at):
        parent = selection_info['parent']
        indices = selection_info['indices']
        moving_items = [parent[index] for index in indices]
        adjusted_insert_at = insert_at
        for index in reversed(indices):
            parent.pop(index)
            if index < adjusted_insert_at:
                adjusted_insert_at -= 1
        for offset, value in enumerate(moving_items):
            parent.insert(adjusted_insert_at + offset, value)
        new_paths = [selection_info['parent_path'] + [adjusted_insert_at + offset] for offset in range(len(moving_items))]
        self._refresh_editor_structure()
        self._select_tree_paths(new_paths)
        return new_paths

    def _on_tree_drag_start(self, event):
        item_id = self.structure.identify_row(event.y)
        if not item_id:
            self.tree_drag_state = None
            return
        selection_info = self._get_selected_list_item_info()
        if not selection_info:
            self.tree_drag_state = None
            return
        item_path = self.tree_paths.get(item_id, [])
        if item_path not in selection_info['paths']:
            self.tree_drag_state = None
            return
        self.tree_drag_state = {'paths': selection_info['paths']}

    def _on_tree_drag_motion(self, event):
        if not self.tree_drag_state:
            return
        target_item = self.structure.identify_row(event.y)
        if target_item:
            self.structure.focus(target_item)

    def _on_tree_drag_release(self, event):
        if not self.tree_drag_state or self.editor_data is None:
            self.tree_drag_state = None
            return
        selection_info = self._get_selected_list_item_info()
        self.tree_drag_state = None
        if not selection_info:
            return
        target_item = self.structure.identify_row(event.y)
        if not target_item:
            return
        target_path = self.tree_paths.get(target_item, [])
        if target_path in selection_info['paths']:
            return
        if target_path == selection_info['parent_path']:
            insert_at = len(selection_info['parent'])
        else:
            target_parent_info = self._get_parent_info(target_path)
            if not target_parent_info or target_parent_info[1] != 'list' or target_path[:-1] != selection_info['parent_path']:
                self.editor_status_var.set('Drag and drop works within the same list')
                return
            insert_at = target_path[-1]
            bbox = self.structure.bbox(target_item)
            if bbox and event.y > bbox[1] + (bbox[3] / 2.0):
                insert_at += 1
        self._move_list_items_to_index(selection_info, insert_at)
        self.editor_status_var.set('Moved {} node{} by drag and drop'.format(len(selection_info['indices']), '' if len(selection_info['indices']) == 1 else 's'))

    def _update_editor_actions_state(self):
        selection = self.structure.selection()
        if not selection or self.editor_data is None:
            if hasattr(self, 'pick_region_button'):
                self.pick_region_button.configure(state='disabled')
            if hasattr(self, 'pick_step_image_button'):
                self.pick_step_image_button.configure(state='disabled')
            if hasattr(self, 'pick_condition_image_button'):
                self.pick_condition_image_button.configure(state='disabled')
            self.editor_help_var.set('Select a node to edit it. For step lists, use Quick Add and Move buttons.')
            return
        if len(selection) > 1:
            if hasattr(self, 'pick_region_button'):
                self.pick_region_button.configure(state='disabled')
            if hasattr(self, 'pick_step_image_button'):
                self.pick_step_image_button.configure(state='disabled')
            if hasattr(self, 'pick_condition_image_button'):
                self.pick_condition_image_button.configure(state='disabled')
            selection_info = self._get_selected_list_item_info()
            if selection_info:
                self.editor_help_var.set('Multiple list items selected. Drag to reorder, Ctrl+C/Ctrl+V to duplicate, Delete to remove.')
            else:
                self.editor_help_var.set('Multiple nodes selected. Batch actions work only for items from the same list.')
            return
        path_parts = self.tree_paths.get(selection[0], [])
        value = self._get_by_path(path_parts)
        if isinstance(value, list):
            if hasattr(self, 'pick_region_button'):
                self.pick_region_button.configure(state='disabled')
            if hasattr(self, 'pick_step_image_button'):
                self.pick_step_image_button.configure(state='disabled')
            if hasattr(self, 'pick_condition_image_button'):
                self.pick_condition_image_button.configure(state='disabled')
            self.editor_help_var.set('List selected. Add new steps here, or select an item to duplicate and move it.')
            return
        parent_info = self._get_parent_info(path_parts)
        if parent_info and parent_info[1] == 'list' and not isinstance(value, dict):
            if hasattr(self, 'pick_region_button'):
                self.pick_region_button.configure(state='disabled')
            if hasattr(self, 'pick_step_image_button'):
                self.pick_step_image_button.configure(state='disabled')
            if hasattr(self, 'pick_condition_image_button'):
                self.pick_condition_image_button.configure(state='disabled')
            self.editor_help_var.set('List item selected. You can edit it, duplicate it, or move it up and down.')
            return
        if isinstance(value, dict):
            if hasattr(self, 'pick_region_button'):
                self.pick_region_button.configure(state='normal' if self._is_region_node_selected() else 'disabled')
            self._refresh_step_form_controls()
            self._refresh_condition_form_controls()
            self.editor_help_var.set('Object selected. Edit raw JSON for this block, or add children below.')
            return
        if hasattr(self, 'pick_region_button'):
            self.pick_region_button.configure(state='disabled')
        if hasattr(self, 'pick_step_image_button'):
            self.pick_step_image_button.configure(state='disabled')
        if hasattr(self, 'pick_condition_image_button'):
            self.pick_condition_image_button.configure(state='disabled')
        self.editor_help_var.set('Scalar selected. Edit the value directly and apply it.')

    def _is_region_node_selected(self):
        selection = self.structure.selection()
        if not selection:
            return False
        path_parts = self.tree_paths.get(selection[0], [])
        return len(path_parts) == 2 and path_parts[0] == 'regions' and isinstance(self._get_by_path(path_parts), dict)

    def _start_region_pick(self):
        if not self._is_region_node_selected():
            self.editor_status_var.set('Select a regions.<name> node first')
            return
        if self.last_frame is None:
            self.editor_status_var.set('Refresh Preview first')
            return
        selection = self.structure.selection()
        self.region_pick_path = list(self.tree_paths.get(selection[0], []))
        self.preview_pick_mode = 'region'
        self.region_pick_active = True
        self.canvas_drag_start = None
        if self.canvas_drag_rect_id is not None:
            self.canvas.delete(self.canvas_drag_rect_id)
            self.canvas_drag_rect_id = None
        self.editor_status_var.set('Drag on preview to set region')
        self._show_canvas_crosshair(True)

    def _start_image_pick(self):
        image_key = self._current_editor_image_capture_key()
        if not image_key:
            self.editor_status_var.set('Select or enter an image key first')
            return
        if self.last_frame is None:
            self.editor_status_var.set('Refresh Preview first')
            return
        self.preview_pick_mode = 'image'
        self.region_pick_path = None
        self.region_pick_active = True
        self.canvas_drag_start = None
        if self.canvas_drag_rect_id is not None:
            self.canvas.delete(self.canvas_drag_rect_id)
            self.canvas_drag_rect_id = None
        self.editor_status_var.set('Drag on preview to capture {}'.format(image_key))
        self._show_canvas_crosshair(True)

    def _show_canvas_crosshair(self, enabled):
        self.canvas.configure(cursor='crosshair' if enabled else '')

    def _canvas_to_frame_point(self, x, y):
        transform = self.preview_transform or {}
        scale = transform.get('scale') or 1.0
        offset_x = transform.get('offset_x', 0)
        offset_y = transform.get('offset_y', 0)
        frame_w = transform.get('frame_w', 1)
        frame_h = transform.get('frame_h', 1)
        px = int((x - offset_x) / scale)
        py = int((y - offset_y) / scale)
        px = max(0, min(frame_w - 1, px))
        py = max(0, min(frame_h - 1, py))
        return px, py

    def _on_canvas_motion(self, event):
        if self.preview_transform is None:
            self.cursor_var.set('cursor: -')
            return
        x, y = self._canvas_to_frame_point(event.x, event.y)
        self.cursor_var.set('cursor: ({}, {})'.format(x, y))

    def _on_canvas_leave(self, _event=None):
        self.cursor_var.set('cursor: -')

    def _on_canvas_press(self, event):
        if not self.region_pick_active:
            return
        self.canvas_drag_start = (event.x, event.y)
        if self.canvas_drag_rect_id is not None:
            self.canvas.delete(self.canvas_drag_rect_id)
        self.canvas_drag_rect_id = self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline='#ff5a36', width=2, dash=(4, 2))

    def _on_canvas_drag(self, event):
        if not self.region_pick_active or self.canvas_drag_start is None or self.canvas_drag_rect_id is None:
            return
        x1, y1 = self.canvas_drag_start
        self.canvas.coords(self.canvas_drag_rect_id, x1, y1, event.x, event.y)

    def _on_canvas_release(self, event):
        if not self.region_pick_active or self.canvas_drag_start is None:
            return
        x1, y1 = self.canvas_drag_start
        x2, y2 = event.x, event.y
        pick_mode = self.preview_pick_mode
        self.region_pick_active = False
        self.preview_pick_mode = None
        self.canvas_drag_start = None
        self._show_canvas_crosshair(False)
        if self.canvas_drag_rect_id is not None:
            self.canvas.delete(self.canvas_drag_rect_id)
            self.canvas_drag_rect_id = None
        fx1, fy1 = self._canvas_to_frame_point(min(x1, x2), min(y1, y2))
        fx2, fy2 = self._canvas_to_frame_point(max(x1, x2), max(y1, y2))
        region = {
            'x': int(fx1),
            'y': int(fy1),
            'w': max(1, int(fx2 - fx1)),
            'h': max(1, int(fy2 - fy1)),
        }
        if pick_mode == 'image':
            self._save_image_from_preview_region(region)
            return
        if not self.region_pick_path:
            return
        parent, parent_type = self._get_parent_info(self.region_pick_path)
        if parent_type == 'dict':
            parent[self.region_pick_path[-1]] = region
            self.editor_status_var.set('Region updated from preview')
            path_parts = list(self.region_pick_path)
            self.region_pick_path = None
            self._refresh_editor_structure()
            self._select_tree_path(path_parts)
            self.last_overlay_regions = [overlay for overlay in self.last_overlay_regions if overlay.get('name') != path_parts[-1]]
            self.last_overlay_regions.append({'name': path_parts[-1], **region})
            if self.last_frame is not None:
                self._render_frame(self.last_frame, None)

    def _resolve_selected_preview_region(self, path_parts, value):
        if not isinstance(self.editor_data, dict):
            return None
        regions = self.editor_data.get('regions') or {}

        if len(path_parts) == 2 and path_parts[0] == 'regions' and isinstance(value, dict):
            return self._normalize_preview_region(value, path_parts[-1])

        if isinstance(value, dict) and value.get('action') == 'tap_region':
            return self._resolve_named_region(value.get('region'))

        if isinstance(value, dict) and value.get('type') == 'region_color':
            return self._normalize_preview_region(value.get('region'), 'condition region')

        if isinstance(value, dict) and value.get('action') in ('if', 'while', 'wait_for'):
            condition = value.get('condition') or {}
            if condition.get('type') == 'region_color':
                return self._normalize_preview_region(condition.get('region'), 'condition region')

        return None

    def _resolve_named_region(self, region_name):
        if not region_name or not isinstance(self.editor_data, dict):
            return None
        region = (self.editor_data.get('regions') or {}).get(region_name)
        return self._normalize_preview_region(region, region_name)

    def _normalize_preview_region(self, region, name=None):
        if not isinstance(region, dict):
            return None
        if not all(key in region for key in ('x', 'y', 'w', 'h')):
            return None
        return {
            'name': name or 'selected',
            'x': int(region['x']),
            'y': int(region['y']),
            'w': int(region['w']),
            'h': int(region['h']),
        }

    def _toggle_trace(self):
        if self.trace_running:
            self.trace_stop_requested = True
            self.status_var.set('status: stopping trace')
            self.trace_button_var.set('Stopping...')
            return

        self.trace_stop_requested = False
        self.trace_command_queue = queue.Queue()
        self.trace_running = True
        self.trace_button_var.set('Stop Trace')
        self.status_var.set('status: starting trace')
        current_path = self.editor_path_var.get().strip() or self.macro_var.get().strip() or self.macro_path
        self._sync_macro_runtime(current_path)
        self.trace_thread = threading.Thread(target=self._run_macro, daemon=True)
        self.trace_thread.start()

    def _run_macro(self):
        current_config = load_runtime_config(self.runtime_args, self.macro_path)
        self.config = current_config
        stats = Stats(current_config)
        driver = create_runtime_driver(current_config)
        runner = MacroRunner(
            current_config,
            stats,
            driver=driver,
            event_listener=self._listener,
            stop_requested=lambda: self.trace_stop_requested,
            command_queue=self.trace_command_queue
        )
        try:
            runner.run_path(self.macro_path)
            self.queue.put({'type': 'worker_done', 'status': 'completed'})
        except Exception as error:
            if error.__class__.__name__ == 'MacroStopRequested':
                self.queue.put({'type': 'worker_done', 'status': 'stopped'})
                return
            write_traceback()
            self.queue.put({'type': 'worker_done', 'status': 'failed', 'error': str(error)})

    def _listener(self, event):
        self.queue.put(event)

    def _tick(self):
        try:
            while True:
                event = self.queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass

        self.root.after(self.QUEUE_POLL_MS, self._tick)

    def _handle_event(self, event):
        event_type = event.get('type')

        if event_type == 'macro_start':
            self._set_trace_context_snapshot(event)
            self.status_var.set('status: running {}'.format(event.get('macro')))
            self.trace_current_macro_path = event.get('path')
            self.last_overlay_regions = []
            self._sync_trace_editor_macro(event.get('path'))
            self._append_log('[MACRO] start {}'.format(event.get('macro')))
            return

        if event_type == 'macro_end':
            self._set_trace_context_snapshot(event)
            self.status_var.set('status: finished {} result={}'.format(event.get('macro'), event.get('result')))
            self._append_log('[MACRO] end {} result={}'.format(event.get('macro'), event.get('result')))
            return

        if event_type == 'step_start':
            self._set_trace_context_snapshot(event)
            step = event.get('step', {})
            self.step_var.set('step: {}'.format(self._format_step(step)))
            self._sync_trace_editor_macro(event.get('macro'))
            self._highlight_trace_step(event.get('step_path'))
            if step.get('image'):
                self._set_current_image(step.get('image'))
            self._append_log('[STEP] {}'.format(self._format_step(step)), limit=120)
            return

        if event_type == 'step_end':
            self._set_trace_context_snapshot(event)
            return

        if event_type == 'context_update':
            self._set_trace_context_snapshot(event)
            self.trace_context_status_var.set('Updated: {}={}'.format(event.get('key'), json.dumps(event.get('value'))))
            self._append_log('[CONTEXT] set {} {}={}'.format(event.get('source'), event.get('key'), self._value_to_editor_text(event.get('value'))), limit=120)
            return

        if event_type == 'context_error':
            self.trace_context_status_var.set('Update failed: {}'.format(event.get('message') or 'unknown error'))
            self._append_log('[ERROR] context update failed: {}'.format(event.get('message') or 'unknown error'))
            return

        if event_type == 'screen_update':
            frame = event.get('frame')
            if frame is not None:
                self.last_frame = frame
                self._render_frame(frame, self.last_region)
            return

        if event_type == 'preview_refresh_done':
            if event.get('ok'):
                frame = event.get('frame')
                self._log_preview_debug('preview_refresh_done ok canvas={}x{} frame_shape={}'.format(self.canvas.winfo_width(), self.canvas.winfo_height(), getattr(frame, 'shape', None)))
                if frame is not None:
                    self.last_frame = frame
                    self._render_frame(frame, self.last_region)
                shape = event.get('shape')
                dump_path = event.get('dump_path')
                self.editor_status_var.set('Preview refreshed{} {}'.format(' {}'.format(shape) if shape else '', dump_path or ''))
                if not self.trace_running:
                    self.status_var.set('status: preview ready')
            else:
                self.editor_status_var.set('Preview refresh failed: {}'.format(event.get('error') or 'could not capture screen'))
                self.status_var.set('status: preview unavailable')
                self._show_canvas_message('Preview unavailable\nCheck emulator/ADB and try Refresh Preview.')
                self.canvas.image = None
            return

        if event_type in ('condition_image', 'image_action'):
            self._set_current_image(event.get('image') or '-')
            found = bool(event.get('found'))
            region = event.get('region')
            self.last_region = region if found else None
            self.result_var.set('result: {}{}'.format('FOUND' if found else 'MISS', self._format_region(region, found)))
            self.probe_var.set('probe: -')
            frame = event.get('frame')
            if frame is not None:
                self.last_frame = frame
                self._render_frame(frame, self.last_region)
            self._append_log('[{}] {} {}'.format(event_type, self.current_image, 'FOUND' if found else 'MISS'), limit=120)
            return

        if event_type == 'condition_region_color':
            region = event.get('region')
            found = bool(event.get('found'))
            color = event.get('color') or []
            self.last_region = region
            self._set_current_image('-')
            self.result_var.set('result: {}{}'.format('MATCH' if found else 'MISS', self._format_region(region, True)))
            self.probe_var.set('probe: color={}'.format(color))
            frame = event.get('frame')
            if frame is not None:
                self.last_frame = frame
                self._render_frame(frame, self.last_region)
            self._append_log('[condition_region_color] {} {}'.format(color, 'MATCH' if found else 'MISS'), limit=120)
            return

        if event_type == 'plugin_call':
            plugin_name = event.get('plugin') or '-'
            self._set_current_image('-')
            self.probe_var.set('probe: plugin={}'.format(plugin_name))
            self._append_log('[PLUGIN] call {}'.format(plugin_name), limit=120)
            return

        if event_type in ('plugin_probe', 'condition_plugin'):
            plugin_name = event.get('plugin') or '-'
            region = event.get('region')
            found = bool(event.get('found'))
            color = event.get('color') or []
            self.last_region = region
            self._set_current_image('-')
            self.result_var.set('result: {}{}'.format('MATCH' if found else 'MISS', self._format_region(region, region is not None)))
            probe_name = event.get('probe') or plugin_name
            extra_parts = []
            for key in ('fill_ratio', 'current_value', 'remaining_value', 'target_value', 'selected_supply', 'supply_value'):
                if event.get(key) is not None:
                    extra_parts.append('{}={}'.format(key, event.get(key)))
            extra_text = ' ' + ' '.join(extra_parts) if extra_parts else ''
            self.probe_var.set('probe: {} color={}{}'.format(probe_name, color, extra_text))
            frame = event.get('frame')
            if frame is not None:
                self.last_frame = frame
                self._render_frame(frame, self.last_region)
            self._append_log('[PLUGIN] {} {} {}{}'.format(plugin_name, probe_name, 'MATCH' if found else 'MISS', extra_text), limit=120)
            return

        if event_type == 'macro_stopped':
            self.status_var.set('status: stop requested')
            return

        if event_type == 'worker_done':
            self.trace_running = False
            self.trace_stop_requested = False
            self.trace_button_var.set('Start Trace')
            if event.get('status') == 'failed':
                self.status_var.set('status: failed {}'.format(event.get('error')))
                self._append_log('[ERROR] {}'.format(event.get('error')))
            elif event.get('status') == 'stopped':
                self.status_var.set('status: stopped')
                self._append_log('[MACRO] stopped by user')
            else:
                self.status_var.set('status: completed')
            return

    def _sync_trace_editor_macro(self, macro_path):
        if not macro_path:
            return
        normalized_path = os.path.abspath(macro_path)
        current_path = os.path.abspath(self.editor_path_var.get().strip()) if self.editor_path_var.get().strip() else ''
        if current_path == normalized_path:
            return
        if os.path.exists(normalized_path):
            self._editor_load_path(normalized_path)

    def _highlight_trace_step(self, step_path):
        if not step_path:
            return
        for item_id, item_path in self.tree_paths.items():
            if item_path == step_path:
                self.structure.selection_set(item_id)
                self.structure.focus(item_id)
                self.structure.see(item_id)
                return

    def _set_current_image(self, image_key):
        self.current_image = image_key
        self.image_var.set('image: {}'.format(self.current_image))
        if not image_key or image_key == '-':
            self.template_label.configure(image='', text='No image')
            self.template_label.image = None
            self.template_photo = None
            return
        self._render_image_preview(image_key, self.template_label, 'template_photo')

    def _render_image_preview(self, image_key, label_widget, photo_attr_name):
        template_path = os.path.join(os.getcwd(), 'assets', self.config.assets['server'], image_key + '.png')
        if not os.path.exists(template_path):
            label_widget.configure(image='', text='Template not found')
            label_widget.image = None
            setattr(self, photo_attr_name, None)
            return

        template = load_bgr_image(template_path)
        if template is None:
            label_widget.configure(image='', text='Failed to load template')
            label_widget.image = None
            setattr(self, photo_attr_name, None)
            return

        max_width = 320
        max_height = 180
        height, width = template.shape[:2]
        scale = min(max_width / float(width), max_height / float(height))
        target_width = max(1, int(width * scale))
        target_height = max(1, int(height * scale))
        preview = cv2.resize(template, (target_width, target_height), interpolation=cv2.INTER_AREA) if (target_width != width or target_height != height) else template
        photo = bgr_to_photoimage(preview)
        setattr(self, photo_attr_name, photo)
        label_widget.configure(image=photo, text='')
        label_widget.image = photo

    def _set_trace_context_snapshot(self, event):
        self.trace_runtime = copy.deepcopy(event.get('runtime') or {})
        self._render_enabled_toggles(self._collect_enabled_flags(self.trace_runtime))

    def _runtime_snapshot_from_value(self, value):
        if isinstance(value, dict):
            return {key: self._runtime_snapshot_from_value(child) for key, child in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._runtime_snapshot_from_value(child) for child in value]
        if hasattr(value, '__dict__'):
            return {
                key: self._runtime_snapshot_from_value(child)
                for key, child in vars(value).items()
                if not key.startswith('_')
            }
        return copy.deepcopy(value)

    def _collect_enabled_flags(self, value, prefix=''):
        results = []
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                child_prefix = '{}.{}'.format(prefix, child_key) if prefix else child_key
                if child_key == 'enabled':
                    results.append((child_prefix, bool(child_value)))
                results.extend(self._collect_enabled_flags(child_value, child_prefix))
        elif isinstance(value, list):
            for index, child_value in enumerate(value):
                child_prefix = '{}[{}]'.format(prefix, index)
                results.extend(self._collect_enabled_flags(child_value, child_prefix))
        return results

    def _render_enabled_toggles(self, flags):
        for child in self.trace_enabled_container.winfo_children():
            child.destroy()
        self.trace_enabled_vars = {}
        if not flags:
            ttk.Label(self.trace_enabled_container, text='No enabled flags found in runtime.').pack(anchor='w')
            return
        for key, value in sorted(flags):
            var = tk.BooleanVar(value=value)
            self.trace_enabled_vars[key] = var
            ttk.Checkbutton(
                self.trace_enabled_container,
                text=key,
                variable=var,
                command=lambda path=key, state_var=var: self._apply_enabled_toggle(path, state_var)
            ).pack(anchor='w')

    def _apply_enabled_toggle(self, key, state_var):
        value = bool(state_var.get())
        if not self._persist_enabled_toggle(key, value):
            self.trace_context_status_var.set('Failed to save {}={}'.format(key, str(value).lower()))
            return
        if self.trace_running:
            self.trace_command_queue.put({
                'type': 'set_context',
                'source': 'runtime',
                'key': key,
                'value': value,
            })
            self.trace_context_status_var.set('Saved and queued: {}={}'.format(key, str(value).lower()))
        else:
            self.trace_context_status_var.set('Saved: {}={}'.format(key, str(value).lower()))

    def _append_log(self, line, limit=200):
        self.log_lines.append(line)
        if len(self.log_lines) > limit:
            self.log_lines = self.log_lines[-limit:]
        self.log_box.configure(state='normal')
        self.log_box.delete('1.0', tk.END)
        for index, entry in enumerate(self.log_lines):
            tags = self._log_tags_for_line(entry)
            self.log_box.insert(tk.END, entry, tags)
            if index < len(self.log_lines) - 1:
                self.log_box.insert(tk.END, '\n')
        self.log_box.configure(state='disabled')
        self.log_box.see(tk.END)

    def _log_tags_for_line(self, line):
        tags = []
        if line.startswith('[ERROR]'):
            tags.append('log_error')
        elif line.startswith('[MACRO]'):
            tags.append('log_macro')
        elif line.startswith('[STEP]'):
            tags.append('log_step')
        elif line.startswith('[condition_region_color]') or line.startswith('[PLUGIN]'):
            tags.append('log_color')
        if 'FOUND' in line or 'MATCH' in line:
            tags.append('log_found')
        elif 'MISS' in line:
            tags.append('log_miss')
        return tuple(tags)

    def _format_step(self, step):
        action = step.get('action', '-')
        if action in ('set',):
            return '{} var={} value={}'.format(action, step.get('var'), self._value_to_editor_text(step.get('value')))
        if action in ('increment',):
            return '{} var={} amount={}'.format(action, step.get('var'), step.get('amount', 1))
        if action in ('return',):
            return '{} value={}'.format(action, self._value_to_editor_text(step.get('value')))
        if action in ('sleep', 'wait_update_screen'):
            return '{} seconds={}'.format(action, step.get('seconds'))
        if action in ('repeat',):
            return '{} times={}'.format(action, step.get('times', 1))
        if action in ('if', 'while', 'wait_for'):
            return '{} condition={}'.format(action, self._describe_condition(step.get('condition', {})))
        if action in ('plugin',):
            return '{} plugin={}'.format(action, step.get('plugin'))
        if 'image' in step:
            return '{} image={}'.format(action, step['image'])
        if 'region' in step:
            return '{} region={}'.format(action, step['region'])
        if 'routine' in step:
            return '{} routine={}'.format(action, step['routine'])
        if 'path' in step:
            return '{} path={}'.format(action, step['path'])
        return action

    def _format_region(self, region, found):
        if not found or region is None:
            return ''
        return ' @ ({x}, {y}, {w}, {h})'.format(**region)

    def _on_canvas_resize(self, _event=None):
        self._log_preview_debug('canvas resize {}x{}'.format(self.canvas.winfo_width(), self.canvas.winfo_height()))
        if self.last_frame is not None:
            self._render_frame(self.last_frame, self.last_region)
        elif self.canvas_text_id is None:
            self._show_canvas_message('Preview hidden\nPress Refresh Preview.')
        else:
            self._ensure_preview_frame()

    def _show_canvas_message(self, message):
        self.canvas.delete('all')
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        self.canvas_text_id = self.canvas.create_text(
            width // 2,
            height // 2,
            text=message,
            fill='#f3f4f6',
            justify='center',
            font=('Segoe UI', 12)
        )
        self.canvas_image_id = None

    def _render_frame(self, frame, region):
        if frame is None:
            self._log_preview_debug('render skipped: frame is None')
            return
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        if canvas_width < 50 or canvas_height < 50:
            parent_width = self.canvas.master.winfo_width() if self.canvas.master is not None else 0
            parent_height = self.canvas.master.winfo_height() if self.canvas.master is not None else 0
            root_width = self.root.winfo_width()
            root_height = self.root.winfo_height()
            canvas_width = max(canvas_width, parent_width, root_width - 480, 800)
            canvas_height = max(canvas_height, parent_height, root_height - 40, 600)
            self._log_preview_debug('render fallback canvas={}x{} parent={}x{} root={}x{}'.format(canvas_width, canvas_height, parent_width, parent_height, root_width, root_height))
        else:
            self._log_preview_debug('render start canvas={}x{} frame_shape={}'.format(canvas_width, canvas_height, getattr(frame, 'shape', None)))

        preview = frame.copy()
        for overlay in self.last_overlay_regions:
            x1 = overlay['x']
            y1 = overlay['y']
            x2 = x1 + overlay['w']
            y2 = y1 + overlay['h']
            cv2.rectangle(preview, (x1, y1), (x2, y2), (255, 180, 40), 2)
            cv2.putText(
                preview,
                overlay['name'],
                (x1, max(24, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 180, 40),
                2,
                cv2.LINE_AA
            )

        if self.selected_preview_region is not None:
            x1 = self.selected_preview_region['x']
            y1 = self.selected_preview_region['y']
            x2 = x1 + self.selected_preview_region['w']
            y2 = y1 + self.selected_preview_region['h']
            cv2.rectangle(preview, (x1, y1), (x2, y2), (70, 160, 255), 3)
            cv2.putText(
                preview,
                self.selected_preview_region.get('name', 'selected'),
                (x1, max(24, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (70, 160, 255),
                2,
                cv2.LINE_AA
            )

        if region is not None:
            x1 = region['x']
            y1 = region['y']
            x2 = x1 + region['w']
            y2 = y1 + region['h']
            cv2.rectangle(preview, (x1, y1), (x2, y2), (40, 220, 120), 3)
            if self.current_image and self.current_image != '-':
                cv2.putText(preview, self.current_image, (x1, max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (40, 220, 120), 2, cv2.LINE_AA)

        max_width = max(canvas_width, 1)
        max_height = max(canvas_height, 1)
        height, width = preview.shape[:2]
        scale = min(max_width / float(width), max_height / float(height)) if max_width > 1 and max_height > 1 else 1.0
        render_width = max(1, int(width * scale))
        render_height = max(1, int(height * scale))
        if scale > 0 and (render_width != width or render_height != height):
            preview = cv2.resize(preview, (render_width, render_height), interpolation=cv2.INTER_AREA)
        else:
            render_width = width
            render_height = height

        offset_x = max(0, (max_width - render_width) // 2)
        offset_y = max(0, (max_height - render_height) // 2)
        self.preview_transform = {
            'scale': scale if scale > 0 else 1.0,
            'offset_x': offset_x,
            'offset_y': offset_y,
            'frame_w': width,
            'frame_h': height,
            'render_w': render_width,
            'render_h': render_height,
        }

        self.last_photo = bgr_to_photoimage(preview)
        self.canvas.delete('all')
        self.canvas_image_id = self.canvas.create_image(offset_x, offset_y, image=self.last_photo, anchor='nw')
        self.canvas.image = self.last_photo
        self.canvas_text_id = None


def build_arg_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', metavar='CONFIG_FILE', help='Use the specified configuration file instead of the default config.json')
    parser.add_argument('-d', '--debug', help='Enables debugging logs.', action='store_true')
    parser.add_argument('-l', '--legacy', help='Enables sed usage.', action='store_true')
    parser.add_argument('--macro', default=os.path.join('macros', 'main_loop.json'), help='Run the specified macro JSON file.')
    return parser


def main():
    args = build_arg_parser().parse_args()
    config = load_runtime_config(args, args.macro)
    create_runtime_driver(config)
    root = tk.Tk()
    MacroViewerApp(root, config, args.macro, runtime_args=args)
    root.mainloop()


if __name__ == '__main__':
    main()
