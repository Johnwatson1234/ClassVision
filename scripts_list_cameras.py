import cv2
import time

def try_index(idx):
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)  # Windows 推荐 DirectShow
    ok, frame = cap.read()
    if not ok or frame is None:
        cap.release()
        return False, None
    h, w = frame.shape[:2]
    print(f"[OK] Camera index {idx}: {w}x{h}")
    # 预览 1 秒，按 q 跳过
    start = time.time()
    while time.time() - start < 5.0:
        ok, frame = cap.read()
        if not ok:
            break
        cv2.imshow(f"index {idx}", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    cv2.destroyAllWindows()
    cap.release()
    return True, (w, h)

if __name__ == "__main__":
    print("Trying camera indices 0..9")
    for i in range(10):
        ok, _ = try_index(i)
        if ok:
            print(f"=> Candidate index: {i}")