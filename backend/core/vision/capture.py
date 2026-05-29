import base64
import logging
from io import BytesIO
from typing import Optional, Tuple

import pyautogui
import pygetwindow as gw
from PIL import Image

log = logging.getLogger(__name__)

def capture_screen(quality: int = 70) -> Tuple[Optional[str], str]:
    """Capture the full screen and the active window title.
    
    Returns:
        (base64_image, active_window_title)
    """
    try:
        # 1. Get active window title
        active_window = gw.getActiveWindow()
        window_title = active_window.title if active_window else "Desktop"
        
        # 2. Take screenshot
        screenshot = pyautogui.screenshot()
        
        # 3. Resize if too large (VLMs often prefer ~768-1024px)
        max_dim = 1024
        if max(screenshot.size) > max_dim:
            screenshot.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            
        # 4. Convert to JPEG base64
        buffered = BytesIO()
        screenshot.save(buffered, format="JPEG", quality=quality)
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        
        return img_str, window_title
        
    except Exception as e:
        log.error(f"Screen capture failed: {e}")
        return None, "Unknown"

if __name__ == "__main__":
    # Test capture
    img, title = capture_screen()
    if img:
        print(f"Captured: {title} ({len(img)} bytes)")
    else:
        print("Capture failed.")
