"""Count clearly visible faces, so the approval card can ask about consent.

OpenCV is imported on first use (media worker only). `count_faces` returns
None when it cannot check, and quality control then says so instead of
reporting zero faces.
"""

from pathlib import Path


def count_faces(frames: list[Path]) -> int | None:
    try:
        import cv2  # media worker only
    except ImportError:
        return None
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    most = 0
    for frame in frames:
        image = cv2.imread(str(frame))
        if image is None:
            continue
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        min_side = max(60, min(gray.shape[:2]) // 12)  # small background faces are not "clear"
        found = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(min_side, min_side))
        most = max(most, len(found))
    return most
