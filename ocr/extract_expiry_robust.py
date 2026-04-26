# extract_expiry_robust.py
import cv2, pytesseract, re, os
from PIL import Image
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

CROP_PATH = os.path.join("ocr_crops", "crop_right_w75_rotCW.png")

def normalize_candidate(s):
    if not s: return None
    s = s.upper().replace('\n',' ').replace(':',' ').strip()
    patterns = [
        r'EXP(?:IRY)?\s*([A-Z]{3,9}\s*\d{4})',
        r'([A-Z]{3,9}\s*\d{4})',
        r'([0-1]?\d[\/\-\.\s]\d{4})',
        r'([0-1]?\d[\/\-\.\s]\d{2})'
    ]
    for p in patterns:
        m = re.search(p, s)
        if m:
            raw = m.group(1).strip()
            # mm/yy -> mm/yyyy
            m2 = re.match(r'(\d{1,2})[\/\-\.\s](\d{2})$', raw)
            if m2:
                mm = int(m2.group(1)); yy = int(m2.group(2))
                yyyy = 2000 + yy if yy < 80 else 1900 + yy
                return f"{mm:02d}/{yyyy}"
            m3 = re.match(r'(\d{1,2})[\/\-\.\s](\d{4})$', raw)
            if m3:
                return f"{int(m3.group(1)):02d}/{m3.group(2)}"
            m4 = re.match(r'([A-Z]{3,9})\s*(\d{2,4})', raw)
            if m4:
                mon = m4.group(1).title(); yr = m4.group(2)
                if len(yr)==2: yr = str(2000 + int(yr))
                return f"{mon} {yr}"
            return raw
    return None

def try_tesseract(pil_img, config):
    txt = pytesseract.image_to_string(pil_img, config=config, lang='eng')
    return txt.strip()

def generate_variants(img):
    # img: BGR loaded by cv2
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    variants = {}

    # raw gray (resized a bit)
    raw = cv2.resize(gray, None, fx=1.3, fy=1.3, interpolation=cv2.INTER_CUBIC)
    variants['raw'] = raw

    # CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)).apply(raw)
    variants['clahe'] = clahe

    # OTSU threshold on CLAHE
    _, otsu = cv2.threshold(clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants['otsu'] = otsu

    # inverted (useful if text is dark on light)
    inv = cv2.bitwise_not(otsu)
    variants['inverted'] = inv

    # median blur + adaptive threshold
    med = cv2.medianBlur(raw, 3)
    adapt = cv2.adaptiveThreshold(med,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,11,2)
    variants['adaptive'] = adapt

    # slight sharpen then otsu
    kernel = cv2.array = None
    try:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3,3))
    except:
        kernel = None
    # small unsharp
    kernel_sharp = (1/9) * cv2.getGaussianKernel(3,0) if False else None
    # simple sharpening via filter
    kernel2 = cv2.filter2D(raw, -1, cv2.getDerivKernels(1,0,3)[0]) if False else None

    return variants

def run_all():
    if not os.path.exists(CROP_PATH):
        print("Crop not found:", CROP_PATH); return
    img = cv2.imread(CROP_PATH)
    if img is None:
        print("Failed to read crop:", CROP_PATH); return

    variants = generate_variants(img)
    psm_list = [7,6,3]   # try single line, block, auto
    whitelist = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/.- "
    candidates = []

    for vname, var in variants.items():
        pil = Image.fromarray(var)
        for psm in psm_list:
            cfg = f"--psm {psm} --oem 3 -c tessedit_char_whitelist={whitelist}"
            txt = try_tesseract(pil, cfg)
            parsed = normalize_candidate(txt)
            candidates.append({'variant':vname, 'psm':psm, 'raw':txt, 'parsed':parsed})

    # Print candidates (sorted: prefer parsed not None)
    print("\nAll OCR attempts (parsed expiry if any):\n")
    for c in candidates:
        print(f"{c['variant']:<10} psm={c['psm']} => parsed={c['parsed']}\n    raw: {c['raw'][:120]}\n")

    # pick first non-empty parsed
    for c in candidates:
        if c['parsed']:
            print("\n=== CHOSEN EXPIRY ===\n", c['parsed'])
            return c['parsed']
    print("\nNo expiry parsed from any variant.")
    return None

if __name__ == "__main__":
    run_all()
