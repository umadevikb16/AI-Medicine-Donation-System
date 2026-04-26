# extract_expiry_selected.py
import pytesseract
from PIL import Image
import cv2, re, os, sys

# Adjust path if your tesseract is installed elsewhere
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def run_tess(path, config="--psm 7 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/:.-"):
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(path)
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    text = pytesseract.image_to_string(pil, config=config, lang='eng')
    return text.strip()

def normalize_expiry(raw):
    if not raw: 
        return None
    s = raw.upper().replace('\n',' ').replace(':',' ').strip()
    # try patterns
    patterns = [
        r'EXP(?:IRY)?\s*([A-Z]{3,9}\s*\d{4})',   # EXP JUL 2026
        r'([A-Z]{3,9}\s*\d{4})',                 # JUL 2026
        r'([0-1]?\d[\/\-\.\s]\d{4})',            # 07/2026
        r'([0-1]?\d[\/\-\.\s]\d{2})'             # 07/26
    ]
    for p in patterns:
        m = re.search(p, s)
        if m:
            mval = m.group(1).strip()
            # mm/yy -> mm/yyyy
            m2 = re.match(r'(\d{1,2})[\/\-\.\s](\d{2})$', mval)
            if m2:
                mm = int(m2.group(1)); yy = int(m2.group(2))
                yyyy = 2000 + yy if yy < 80 else 1900 + yy
                return f"{mm:02d}/{yyyy}"
            m3 = re.match(r'(\d{1,2})[\/\-\.\s](\d{4})$', mval)
            if m3:
                return f"{int(m3.group(1)):02d}/{m3.group(2)}"
            # Month name + year
            m4 = re.match(r'([A-Z]{3,9})\s*(\d{2,4})', mval)
            if m4:
                mon = m4.group(1).title(); yr = m4.group(2)
                if len(yr) == 2: yr = str(2000 + int(yr))
                return f"{mon} {yr}"
            return mval
    return None

if __name__ == "__main__":
    # path to the clear crop you identified
    crop_path = os.path.join("ocr_crops", "crop_right_w75_rotCW.png")
    if not os.path.exists(crop_path):
        print("Crop not found:", crop_path)
        sys.exit(1)

    raw = run_tess(crop_path)
    print("\n--- RAW OCR (right crop) ---\n")
    print(raw)
    parsed = normalize_expiry(raw)
    print("\n--- PARSED EXPIRY ---\n", parsed)
def get_expiry_from_image(image_path):
    raw_text = run_tess(image_path)
    expiry = normalize_expiry(raw_text)
    return expiry
