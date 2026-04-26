# ocr_try_more_crops.py
import cv2, pytesseract, sys, re, os
from PIL import Image
import numpy as np

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def save_img(path, img):
    cv2.imwrite(path, img)

def preprocess_for_text_gray(gray, upscale=1.3):
    h, w = gray.shape[:2]
    if upscale != 1.0:
        gray = cv2.resize(gray, (int(w*upscale), int(h*upscale)), interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)).apply(gray)
    blur = cv2.medianBlur(clahe, 3)
    kernel = np.array([[0,-1,0],[-1,5,-1],[0,-1,0]])
    sharp = cv2.filter2D(blur, -1, kernel)
    _, th = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return th

def run_tess(pil_img, config="--psm 7 --oem 3"):
    text = pytesseract.image_to_string(pil_img, lang='eng', config=config)
    data = pytesseract.image_to_data(pil_img, lang='eng', config=config, output_type=pytesseract.Output.DICT)
    return text.strip(), data

def find_expiry_from_string(s):
    if not s: return None
    s_up = s.replace('\n',' ').upper()
    patterns = [
        r'EXP(?:IRY|):?\s*(\d{1,2}[\/\-\.\s]\d{2,4})',
        r'(\d{1,2}[\/\-\.\s]\d{4})',
        r'([A-Z]{3,9}\s*\d{4})',
        r'(\d{1,2}[\/\-\.\s]\d{2})'
    ]
    for p in patterns:
        m = re.search(p, s_up)
        if m:
            raw = m.group(1).strip()
            # normalize mm/yy -> mm/yyyy
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

def get_confident_words(data, conf_thresh=40):
    words = []
    for i, w in enumerate(data.get('text', [])):
        try:
            conf = int(float(data.get('conf', [])[i]))
        except:
            conf = -1
        if w.strip() and conf > conf_thresh:
            words.append((w.strip(), conf))
    return words

def try_right_strips(img_bgr, out_dir):
    h, w = img_bgr.shape[:2]
    results = []
    # different right widths to try (fraction of width taken from right side)
    widths = [0.90, 0.88, 0.85, 0.82, 0.80, 0.75, 0.70]  # try narrower to wider until expiry appears
    for frac in widths:
        left = int(w * frac)
        crop = img_bgr[0:h, left:w]
        # try both rotations
        for rot_name, rot_fn in [('rotCW', lambda x: cv2.rotate(x, cv2.ROTATE_90_CLOCKWISE)),
                                 ('rotCCW', lambda x: cv2.rotate(x, cv2.ROTATE_90_COUNTERCLOCKWISE))]:
            cimg = rot_fn(crop)
            gray = cv2.cvtColor(cimg, cv2.COLOR_BGR2GRAY)
            prep = preprocess_for_text_gray(gray, upscale=1.3)
            fname = os.path.join(out_dir, f"crop_right_w{int(frac*100)}_{rot_name}.png")
            save_img(fname, prep)
            pil = Image.fromarray(prep)
            # allow digits and letters and /.- in whitelist
            cfg = "--psm 7 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/.-"
            text, data = run_tess(pil, config=cfg)
            conf_words = get_confident_words(data, conf_thresh=30)
            expiry = find_expiry_from_string(text)
            results.append({'frac': frac, 'rot': rot_name, 'file': fname, 'text': text, 'conf': conf_words, 'expiry': expiry})
    return results

def try_brand_areas(img_bgr, out_dir):
    h, w = img_bgr.shape[:2]
    results = []
    # try several vertical slices around middle-lower area
    areas = [
        (int(h*0.35), int(h*0.75), int(w*0.04), int(w*0.95)),
        (int(h*0.40), int(h*0.78), int(w*0.02), int(w*0.70)),
        (int(h*0.45), int(h*0.82), int(w*0.02), int(w*0.60)),
        (int(h*0.28), int(h*0.65), int(w*0.02), int(w*0.80))
    ]
    i = 0
    for top,bottom,left,right in areas:
        crop = img_bgr[top:bottom, left:right]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        prep = preprocess_for_text_gray(gray, upscale=1.6)
        fname = os.path.join(out_dir, f"crop_brand_{i}.png"); i+=1
        save_img(fname, prep)
        pil = Image.fromarray(prep)
        cfg = "--psm 7 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-"
        text, data = run_tess(pil, config=cfg)
        conf_words = get_confident_words(data, conf_thresh=35)
        results.append({'area_index': i-1, 'file': fname, 'text': text, 'conf': conf_words})
    return results

def full_image_ocr(img_bgr, out_dir):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    prep = preprocess_for_text_gray(gray, upscale=1.2)
    fname = os.path.join(out_dir, "crop_full_preprocessed.png")
    save_img(fname, prep)
    pil = Image.fromarray(prep)
    text, data = run_tess(pil, config="--psm 3 --oem 3")
    conf_words = get_confident_words(data, conf_thresh=30)
    return {'file': fname, 'text': text, 'conf': conf_words}

if __name__ == "__main__":
    img_path = sys.argv[1] if len(sys.argv)>1 else "test_medicine.jpg"
    out_dir = "ocr_crops"
    os.makedirs(out_dir, exist_ok=True)
    img_bgr = cv2.imread(img_path)
    if img_bgr is None:
        print("Image not found:", img_path); sys.exit(1)

    print("Trying multiple right-strips (saved to folder 'ocr_crops'). This may take ~10-20s.")
    right_results = try_right_strips(img_bgr, out_dir)
    # show hits for expiry
    for r in right_results:
        print(f"\nRIGHT frac={r['frac']}, rot={r['rot']}, file={r['file']}")
        print("Detected expiry:", r['expiry'])
        print("First 160 chars:", (r['text'][:160]).replace('\n',' '))
        print("Confident words:", r['conf'][:10])

    print("\nTrying multiple brand-area crops...")
    brand_results = try_brand_areas(img_bgr, out_dir)
    for b in brand_results:
        print(f"\nBRAND crop file={b['file']}")
        print("First 160 chars:", (b['text'][:160]).replace('\n',' '))
        print("Confident words:", b['conf'][:12])

    print("\nFull image (fallback):")
    full = full_image_ocr(img_bgr, out_dir)
    print("file:", full['file'])
    print("First 300 chars:", (full['text'][:300]).replace('\n',' '))
    print("Confident words:", full['conf'][:20])

    print("\nDONE. Please open the images inside the 'ocr_crops' folder and tell me which crop shows the expiry clearly (or paste the terminal expiry values above).")
