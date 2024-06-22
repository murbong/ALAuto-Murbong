import cv2

from modules.commission import CommissionModule
from modules.headquarters import HeadquartersModule
from util.config import Config

img = cv2.imread("./Screenshot_2024.06.22_17.14.38.966.png",cv2.IMREAD_COLOR)

# template = cv2.imread('assets/KR/commission/button_go.png', cv2.IMREAD_COLOR)
# a,w,h = template.shape[::-1]
# match = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
# min_val, max_val, min_loc,max_loc = cv2.minMaxLoc(match)
# bottom_right = (max_loc[0] + w, max_loc[1] + h)

config = Config('config.ini')

commisionTest = CommissionModule(config,None)

headquaterTest = HeadquartersModule (config,None)

for region in commisionTest.region:
    value = commisionTest.region[region]

    x = value.x
    y = value.y
    w = value.w
    h = value.h
    cv2.putText(img,region,(x,y),cv2.FONT_HERSHEY_SIMPLEX,0.5,(255,0,0),2)
    cv2.rectangle(img,(x,y),(x+w,y+h),255,2)

# for region in headquaterTest.supply_region:
#     x = region.x
#     y = region.y
#     w = region.w
#     h = region.h
#     cv2.putText(img,"1",(x,y),cv2.FONT_HERSHEY_SIMPLEX,0.5,(255,0,0),2)
#     cv2.rectangle(img,(x,y),(x+w,y+h),255,2)

cv2.imshow('image',img)
cv2.waitKey(0)
cv2.destroyAllWindows()