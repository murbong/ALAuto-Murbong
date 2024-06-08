import cv2


img = cv2.imread("./test2.png",cv2.IMREAD_COLOR)

template = cv2.imread('assets/KR/commission/button_go.png', cv2.IMREAD_COLOR)

a,w,h = template.shape[::-1]

match = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)

min_val, max_val, min_loc,max_loc = cv2.minMaxLoc(match)

bottom_right = (max_loc[0] + w, max_loc[1] + h)

cv2.rectangle(img,max_loc,bottom_right,255,2)

cv2.imshow('image',img)
cv2.waitKey(0)
cv2.destroyAllWindows()