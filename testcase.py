import cv2

from modules.commission import CommissionModule
from modules.headquarters import HeadquartersModule
from modules.research import ResearchModule
from util.config import Config

img = cv2.imread("./Screenshot_2024.09.12_02.48.00.533.png",cv2.IMREAD_COLOR)

config = Config('config.ini')

commisionTest = CommissionModule(config,None)

headquaterTest = HeadquartersModule (config,None)

researchTest = ResearchModule(config,None)

for region in researchTest.region:
    value = researchTest.region[region]

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