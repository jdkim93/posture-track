"""Physical Windows display bounds, including negative desktop coordinates."""
import ctypes
from ctypes import wintypes


def display_bounds():
    rectangles=[]
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HANDLE,wintypes.HDC,
                                    ctypes.POINTER(wintypes.RECT),wintypes.LPARAM)
    @callback_type
    def collect(monitor,dc,rectangle,data):
        r=rectangle.contents
        rectangles.append((r.left,r.top,r.right,r.bottom))
        return True
    user=ctypes.windll.user32
    user.EnumDisplayMonitors.argtypes=[wintypes.HDC,ctypes.POINTER(wintypes.RECT),callback_type,wintypes.LPARAM]
    user.EnumDisplayMonitors.restype=wintypes.BOOL
    if not user.EnumDisplayMonitors(None,None,collect,0):
        raise OSError("연결된 화면 목록을 읽지 못했습니다")
    return sorted(rectangles,key=lambda r:(0 if r[0]<=0<r[2] and r[1]<=0<r[3] else 1,r[0],r[1]))


def popup_positions(bounds,width,height=40):
    return [(left+(right-left-width)//2,top+24) for left,top,right,bottom in bounds
            if right-left>=width and bottom-top>=height+24]
