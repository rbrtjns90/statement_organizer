#!/usr/bin/env python3
"""
transaction_finder.py
Scan a bank statement PDF and learn a structure-based selector for transaction rows.
No merchant/amount literals are used. Instead, we infer patterns from repeated layout.

Requirements:
  pip install pdfplumber numpy scikit-learn regex pandas
  pip install Pillow  # for --draw flag

Optional (for image-only PDFs):
  Install ocrmypdf, run OCR externally first, or integrate pytesseract.

Usage:
  python transaction_finder.py path/to/statement.pdf [--draw]
"""
import sys, re, math, json, argparse
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional
import pdfplumber
import numpy as np
from sklearn.cluster import KMeans
import pandas as pd

# Drawing imports (optional)
try:
    from PIL import Image, ImageDraw, ImageFont
    DRAWING_AVAILABLE = True
except ImportError:
    DRAWING_AVAILABLE = False
    print("PIL not available. Install with: pip install Pillow")

# ---- Generic shapes (no literals) ----
RE_MONEY = re.compile(r"[+\-]?\d{1,3}(?:,\d{3})*\.\d{2}")  # 1,234.56  -12.00  8.90
RE_DATE = re.compile(
    r"""(?ix)
    (?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)     # 01/31[/2025]
    | (?:\d{4}[/-]\d{1,2}[/-]\d{1,2})          # 2025-01-31
    | (?:\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})    # 31 Jan 2025
    | (?:[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4})  # Jan 31, 2025
    """
)

@dataclass
class Token:
    text: str
    x0: float
    x1: float
    y0: float
    y1: float
    size: float

@dataclass
class Line:
    tokens: List[Token]
    y: float  # baseline / middle
    text: str

def load_page_lines(page) -> List[Line]:
    """
    Reconstruct lines from page.chars, grouping by similar y and merging chars into words/tokens.
    """
    chars = page.chars
    if not chars:
        return []

    # Convert chars -> tokens (rough word grouping on small x-gaps)
    # First, sort by y (top) then x (left)
    chars_sorted = sorted(chars, key=lambda c: (round(c["top"], 1), c["x0"]))
    lines: List[List[dict]] = []
    current: List[dict] = []
    last_top = None
    y_tol = 2.0  # tolerance for being on the same baseline (points)

    for c in chars_sorted:
        if last_top is None or abs(c["top"] - last_top) <= y_tol:
            current.append(c)
            last_top = c["top"] if last_top is None else (last_top + c["top"]) / 2
        else:
            lines.append(current)
            current = [c]
            last_top = c["top"]
    if current:
        lines.append(current)

    # Merge chars into tokens by small x-gaps
    def to_tokens(raw_line: List[dict]) -> List[Token]:
        raw_line = sorted(raw_line, key=lambda c: c["x0"])
        tokens: List[Token] = []
        buf = [raw_line[0]]
        for a, b in zip(raw_line, raw_line[1:]):
            gap = b["x0"] - a["x1"]
            # dynamic threshold: small gap relative to font size
            thr = max(1.5, 0.3 * a["size"])
            if gap <= thr:
                buf.append(b)
            else:
                txt = "".join(ch["text"] for ch in buf)
                t = Token(
                    text=txt,
                    x0=min(ch["x0"] for ch in buf),
                    x1=max(ch["x1"] for ch in buf),
                    y0=min(ch["top"] for ch in buf),
                    y1=max(ch["bottom"] for ch in buf),
                    size=sum(ch["size"] for ch in buf)/len(buf),
                )
                tokens.append(t)
                buf = [b]
        if buf:
            txt = "".join(ch["text"] for ch in buf)
            t = Token(
                text=txt,
                x0=min(ch["x0"] for ch in buf),
                x1=max(ch["x1"] for ch in buf),
                y0=min(ch["top"] for ch in buf),
                y1=max(ch["bottom"] for ch in buf),
                size=sum(ch["size"] for ch in buf)/len(buf),
            )
            tokens.append(t)
        return tokens

    out: List[Line] = []
    for raw in lines:
        toks = [t for t in to_tokens(raw) if t.text.strip()]
        if not toks:
            continue
        y_mid = np.median([(t.y0 + t.y1) / 2 for t in toks])
        text = " ".join(t.text for t in toks)
        out.append(Line(tokens=toks, y=y_mid, text=text))
    return out

def line_features(L: Line, page_width: float) -> Dict[str, Any]:
    txt = L.text
    total = sum(len(t.text) for t in L.tokens)
    n_alpha = sum(sum(ch.isalpha() for ch in t.text) for t in L.tokens)
    n_digit = sum(sum(ch.isdigit() for ch in t.text) for t in L.tokens)
    n_punct = sum(sum((not ch.isalnum() and not ch.isspace()) for ch in t.text) for t in L.tokens)
    alpha_ratio = (n_alpha / total) if total else 0.0

    # shapes (no literals)
    has_money = bool(RE_MONEY.search(txt))
    n_money = len(RE_MONEY.findall(txt))
    has_date = bool(RE_DATE.search(txt))

    # columns: approximate by x-centers
    xs = np.array([(t.x0 + t.x1)/2 for t in L.tokens])
    x_min, x_max = xs.min(), xs.max()
    x_range = x_max - x_min
    rightmost_token = max(L.tokens, key=lambda t: t.x1)
    rightmost_is_money = bool(RE_MONEY.fullmatch(rightmost_token.text.strip()))

    sizes = [t.size for t in L.tokens]
    size_mean = float(np.mean(sizes))
    size_std = float(np.std(sizes))

    return dict(
        len_tokens=len(L.tokens),
        alpha_ratio=alpha_ratio,
        n_digit=n_digit,
        n_punct=n_punct,
        has_money=int(has_money),
        n_money=n_money,
        has_date=int(has_date),
        x_span=x_range / max(1.0, page_width),  # normalized
        rightmost_is_money=int(rightmost_is_money),
        size_mean=size_mean,
        size_std=size_std,
    )

def cluster_transactions(lines: List[Line], page_width: float) -> Tuple[List[int], List[Dict[str, Any]]]:
    # Feature matrix
    feats = [line_features(L, page_width) for L in lines]
    X = np.array([[f["len_tokens"], f["alpha_ratio"], f["n_digit"], f["n_punct"],
                   f["has_money"], f["n_money"], f["has_date"], f["x_span"],
                   f["rightmost_is_money"], f["size_mean"], f["size_std"]] for f in feats], dtype=float)

    # Try k=2..4; pick the k/labels whose "transaction score" is best
    # But ensure we don't try more clusters than we have samples
    n_samples = X.shape[0]
    max_k = min(4, n_samples)
    
    # Handle edge case where we have very few samples
    if n_samples < 2:
        # If we have 0 or 1 samples, just assign all to cluster 0
        labels = np.zeros(n_samples, dtype=int)
        return labels, feats
    
    best = None
    for k in range(2, max_k + 1):
        km = KMeans(n_clusters=k, n_init=8, random_state=42)
        labels = km.fit_predict(X)
        score, best_label = evaluate_clusters(labels, feats, lines)
        if (best is None) or (score > best[0]):
            best = (score, labels, best_label)
    
    # If no clustering was possible (e.g., only 2 samples), use simple binary clustering
    if best is None:
        labels = np.array([0, 1] if n_samples >= 2 else [0])
        return labels, feats
        
    _, labels, chosen = best
    return labels, feats

def evaluate_clusters(labels: np.ndarray, feats: List[Dict[str, Any]], lines: List[Line]) -> Tuple[float, int]:
    """
    Score each cluster and return the best one for transactions.
    Enhanced to filter out summary/header content.
    """
    score_best, label_best = -1e9, -1
    for lab in set(labels):
        idxs = [i for i, L in enumerate(labels) if L == lab]
        F = [feats[i] for i in idxs]
        n = len(F)
        
        # Basic metrics
        money_rate = np.mean([f["has_money"] for f in F])
        right_money_rate = np.mean([f["rightmost_is_money"] for f in F])
        alpha_med = np.median([f["alpha_ratio"] for f in F])
        size_std_med = np.median([f["size_std"] for f in F])
        
        # Check for multiple date patterns in cluster lines
        cluster_lines = [lines[i] for i in idxs]
        multi_date_rate = np.mean([len(RE_DATE.findall(L.text)) >= 2 for L in cluster_lines])
        
        # Filter out obvious non-transaction content
        non_transaction_keywords = [
            'balance', 'payment due', 'credit limit', 'customer service',
            'website', 'phone', 'autopay', 'account message', 'previous balance',
            'new balance', 'minimum payment', 'past due', 'fees charged',
            'cash advance', 'balance transfer', 'www.', '.com', 'http'
        ]
        
        # Count lines that look like actual transactions (have dates AND reasonable descriptions)
        transaction_like = 0
        for line in cluster_lines:
            text_lower = line.text.lower()
            has_date = bool(RE_DATE.search(line.text))
            has_money = bool(RE_MONEY.search(line.text))
            is_summary = any(keyword in text_lower for keyword in non_transaction_keywords)
            
            # Good transaction indicators: date + money + reasonable length + not summary
            if has_date and has_money and len(line.text.strip()) > 10 and not is_summary:
                transaction_like += 1
        
        transaction_rate = transaction_like / n if n > 0 else 0
        
        # Score: prioritize clusters with money, consistent formatting, and transaction-like content
        score = (
            1.0 * n +
            50.0 * money_rate +
            25.0 * right_money_rate +
            5.0 * (0.5 - abs(alpha_med - 0.5)) -  # Prefer balanced alpha ratio
            5.0 * size_std_med +  # Prefer consistent font sizes
            100.0 * transaction_rate  # Big bonus for transaction-like content
        )
        
        # Bonus for high-quality transaction clusters
        if money_rate > 0.8 and n >= 5:
            score += 100.0
            
        # Big bonus for clusters with multiple dates (transaction + posting date)
        if multi_date_rate > 0.8:
            score += 200.0
            
        # Penalty for clusters with too many summary-like lines
        summary_rate = np.mean([any(keyword in line.text.lower() for keyword in non_transaction_keywords) for line in cluster_lines])
        if summary_rate > 0.5:
            score -= 150.0
        
        if score > score_best:
            score_best, label_best = score, lab
    
    return score_best, label_best

def derive_regex_template(lines: List[Line]) -> str:
    """
    Build a generic regex for the cluster: DATE?  DESC  AMOUNT  [BALANCE]?
    Enhanced for Chase statement format with better filtering.
    """
    # Enhanced date pattern to handle multiple formats:
    # - MM/DD/YY or MM/DD/YYYY (Visa format)
    # - Mon DD (Capital One format like "Jan 21")
    # - DD Mon YYYY (like "21 Jan 2024")
    date = r"(?:(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)|(?:\d{4}[/-]\d{1,2}[/-]\d{1,2})|(?:\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})|(?:[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4})|(?:[A-Za-z]{3,9}\s+\d{1,2}))"
    money = r"[+\-]?\d{1,3}(?:,\d{3})*\.\d{2}"

    # Filter lines to only those that look like actual transactions
    filtered_lines = []
    non_transaction_keywords = [
        'balance', 'payment due', 'credit limit', 'customer service',
        'website', 'phone', 'autopay', 'account message', 'previous balance',
        'new balance', 'minimum payment', 'past due', 'fees charged',
        'cash advance', 'balance transfer', 'www.', '.com', 'http'
    ]
    
    for line in lines:
        text_lower = line.text.lower()
        has_date = bool(RE_DATE.search(line.text))
        has_money = bool(RE_MONEY.search(line.text))
        is_summary = any(keyword in text_lower for keyword in non_transaction_keywords)
        
        # Only include lines that look like transactions
        if has_date and has_money and len(line.text.strip()) > 10 and not is_summary:
            filtered_lines.append(line)
    
    # Fall back to original lines if filtering removes everything
    if not filtered_lines:
        filtered_lines = lines
    
    # Check if lines have multiple dates (common in transaction logs)
    has_date_rate = np.mean([bool(RE_DATE.search(L.text)) for L in filtered_lines])
    multiple_dates = np.mean([len(RE_DATE.findall(L.text)) >= 2 for L in filtered_lines])
    
    # Build date part - handle single or multiple dates
    if multiple_dates > 0.5:
        # Two dates pattern (trans date + post date)
        date_part = rf"{date}\s+{date}\s+" if has_date_rate > 0.6 else rf"(?:{date}\s+{date}\s+)?"
    else:
        # Single date pattern
        date_part = rf"{date}\s+" if has_date_rate > 0.6 else rf"(?:{date}\s+)?"

    # If most lines have two money-like tokens (amount + balance), allow two:
    n_money_counts = [len(RE_MONEY.findall(L.text)) for L in filtered_lines]
    two_money_rate = np.mean([c >= 2 for c in n_money_counts]) if n_money_counts else 0

    # Adjust money pattern to handle $ prefix
    money_with_dollar = rf"\${money}|{money}"

    if two_money_rate >= 0.5:
        # Desc is anything between date and first money; then a money; then space and another money
        pattern = rf"^\s*{date_part}(.+?)\s+({money_with_dollar})\s+({money_with_dollar})\s*$"
    else:
        pattern = rf"^\s*{date_part}(.+?)\s+({money_with_dollar})\s*$"

    return pattern

def draw_page_analysis(page, lines: List[Line], labels: List[int], chosen_cluster: int, page_num: int, output_dir: str = "."):
    """Draw a visual analysis of the page with detected transaction lines and guides."""
    if not DRAWING_AVAILABLE:
        print(f"Skipping drawing for page {page_num} - PIL not available")
        return
    
    # Create image with page dimensions
    width, height = int(page.width), int(page.height)
    img = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(img)
    
    # Try to load a font, fall back to default if not available
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
        small_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 10)
    except:
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", 14)
            small_font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", 10)
        except:
            try:
                font = ImageFont.load_default()
                small_font = ImageFont.load_default()
            except:
                font = None
                small_font = None
    
    # Color scheme for different clusters
    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD']
    
    # Draw all lines with cluster colors
    for i, (line, label) in enumerate(zip(lines, labels)):
        color = colors[label % len(colors)]
        
        # Highlight chosen transaction cluster
        if label == chosen_cluster:
            # Draw background rectangle for transaction lines
            y_top = height - line.y - 10
            y_bottom = height - line.y + 10
            draw.rectangle([0, y_top, width, y_bottom], fill='#FFE5E5', outline=None)
            color = '#FF0000'  # Red for chosen cluster
            line_width = 3
        else:
            line_width = 1
        
        # Draw line text with better positioning
        y_pos = height - line.y - 5  # Flip Y coordinate and adjust for better visibility
        if small_font:
            # Draw text with white background for better readability
            text_content = line.text[:100]  # Show more characters
            bbox = draw.textbbox((15, y_pos), text_content, font=small_font)
            draw.rectangle([bbox[0]-2, bbox[1]-1, bbox[2]+2, bbox[3]+1], fill='white', outline='gray')
            draw.text((15, y_pos), text_content, fill=color, font=small_font)
        else:
            # Fallback without font
            draw.text((15, y_pos), line.text[:80], fill=color)
        
        # Draw tokens as rectangles
        for token in line.tokens:
            x0, y0, x1, y1 = token.x0, height - token.y1, token.x1, height - token.y0
            draw.rectangle([x0, y0, x1, y1], outline=color, width=line_width)
    
    # Draw vertical guides at common positions
    money_positions = []
    date_positions = []
    
    for line in lines:
        for token in line.tokens:
            if RE_MONEY.search(token.text):
                money_positions.append(token.x0)
            if RE_DATE.search(token.text):
                date_positions.append(token.x0)
    
    # Draw vertical guides for common money positions
    if money_positions:
        common_money_x = np.median(money_positions)
        draw.line([(common_money_x, 0), (common_money_x, height)], fill='#00AA00', width=2)
        if font:
            draw.text((common_money_x + 5, 10), "$ Guide", fill='#00AA00', font=font)
    
    # Draw vertical guides for common date positions
    if date_positions:
        common_date_x = np.median(date_positions)
        draw.line([(common_date_x, 0), (common_date_x, height)], fill='#0000AA', width=2)
        if font:
            draw.text((common_date_x + 5, 30), "Date Guide", fill='#0000AA', font=font)
    
    # Add legend with background for better visibility
    legend_y = 50
    legend_bg_height = 120
    draw.rectangle([5, legend_y-5, 300, legend_y + legend_bg_height], fill='white', outline='black', width=1)
    
    if font:
        draw.text((10, legend_y), f"Page {page_num} Analysis", fill='black', font=font)
        draw.text((10, legend_y + 20), f"Red: Transaction Cluster ({chosen_cluster})", fill='#FF0000', font=small_font)
        draw.text((10, legend_y + 35), f"Green: Money Guide", fill='#00AA00', font=small_font)
        draw.text((10, legend_y + 50), f"Blue: Date Guide", fill='#0000AA', font=small_font)
        
        # Show cluster stats
        cluster_counts = {}
        for label in labels:
            cluster_counts[label] = cluster_counts.get(label, 0) + 1
        
        stats_y = legend_y + 70
        for i, (cluster_id, count) in enumerate(cluster_counts.items()):
            color = colors[cluster_id % len(colors)] if cluster_id != chosen_cluster else '#FF0000'
            draw.text((10, stats_y + i * 15), f"Cluster {cluster_id}: {count} lines", fill=color, font=small_font)
    else:
        # Fallback without fonts
        draw.text((10, legend_y), f"Page {page_num} Analysis", fill='black')
        draw.text((10, legend_y + 20), f"Red: Transaction Cluster ({chosen_cluster})", fill='#FF0000')
        draw.text((10, legend_y + 35), f"Green: Money Guide", fill='#00AA00')
        draw.text((10, legend_y + 50), f"Blue: Date Guide", fill='#0000AA')
    
    # Save the image
    output_path = f"{output_dir}/page_{page_num:02d}_analysis.png"
    img.save(output_path)
    print(f"Saved page analysis: {output_path}")

def main(pdf_path: str, draw_analysis: bool = False):
    rows: List[Dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        print(f"Processing PDF with {len(pdf.pages)} pages...")
        for pno, page in enumerate(pdf.pages, 1):
            print(f"\n--- Page {pno} ---")
            W = float(page.width)
            lines = load_page_lines(page)
            print(f"Extracted {len(lines)} lines from page {pno}")
            
            if not lines:
                print("No lines found on this page, skipping...")
                continue
                
            # Show first few lines for debugging
            print("Sample lines:")
            for i, line in enumerate(lines[:5]):
                print(f"  {i+1}: {line.text[:80]}...")
            
            labels, feats = cluster_transactions(lines, W)
            print(f"Clustering produced {len(set(labels))} clusters with labels: {set(labels)}")
            
            # pick chosen cluster
            score, chosen = evaluate_clusters(np.array(labels), feats, lines)
            print(f"Chosen cluster for transactions: {chosen} (score: {score:.2f})")
            
            # Show analysis of all clusters
            for lab in set(labels):
                cluster_lines = [L for L, l in zip(lines, labels) if l == lab]
                cluster_feats = [f for f, l in zip(feats, labels) if l == lab]
                money_rate = np.mean([f["has_money"] for f in cluster_feats]) if cluster_feats else 0
                print(f"  Cluster {lab}: {len(cluster_lines)} lines, money_rate: {money_rate:.2f}")
                # Show sample lines from each cluster
                for i, line in enumerate(cluster_lines[:3]):
                    print(f"    Sample {i+1}: {line.text[:60]}...")
            
            txn_lines = [L for L, lab in zip(lines, labels) if lab == chosen]
            print(f"Found {len(txn_lines)} transaction-like lines in chosen cluster")

            if not txn_lines:
                print("No transaction lines found in chosen cluster, skipping...")
                continue

            # Learn a general regex template
            pat = derive_regex_template(txn_lines)
            print(f"Generated regex pattern: {pat}")
            R = re.compile(pat)

            # Parse matched rows into columns
            matched_count = 0
            for i, L in enumerate(txn_lines):
                m = R.match(L.text)
                if not m:
                    if i < 3:  # Show first few failed matches for debugging
                        print(f"  No match for line: {L.text[:100]}...")
                    continue
                matched_count += 1
                if len(m.groups()) == 3:
                    desc, amt, bal = m.group(1), m.group(2), m.group(3)
                else:
                    desc, amt, bal = m.group(1), m.group(2), None
                # Try to extract date (don’t require it in the regex groups to keep flexible)
                dm = RE_DATE.search(L.text)
                date = dm.group(0) if dm else None
                rows.append(dict(page=pno, raw=L.text, date=date, description=desc, amount=amt, balance=bal))
            print(f"Matched {matched_count} out of {len(txn_lines)} transaction lines on page {pno}")
            
            # Draw page analysis if requested
            if draw_analysis:
                draw_page_analysis(page, lines, labels, chosen, pno)

    if not rows:
        print("No transaction-like rows were discovered. Try adjusting OCR/quality or thresholds.")
        return

    # Post-process to filter out obvious non-transaction entries
    filtered_rows = []
    summary_keywords = [
        'previous balance', 'new balance', 'minimum payment', 'payment due',
        'credit limit', 'past due', 'fees charged', 'cash advance', 
        'balance transfer', 'messages for details', 'over the credit limit'
    ]
    
    for row in rows:
        desc_lower = row['description'].lower() if row['description'] else ''
        raw_lower = row['raw'].lower()
        
        # Skip obvious summary/balance lines
        is_summary = any(keyword in desc_lower or keyword in raw_lower for keyword in summary_keywords)
        
        # Keep lines that have dates and look like actual transactions
        has_date = bool(row['date'])
        has_reasonable_desc = len(row['description'].strip()) > 3 if row['description'] else False
        
        if not is_summary and (has_date or has_reasonable_desc):
            filtered_rows.append(row)
        else:
            print(f"Filtered out: {row['raw'][:60]}...")
    
    # Save CSV + show learned template
    df = pd.DataFrame(filtered_rows)
    out_csv = "transactions_extracted.csv"
    df.to_csv(out_csv, index=False)
    print(f"Extracted {len(filtered_rows)} transactions (filtered from {len(rows)} total) → {out_csv}")

    # Also print one learned template (they’re similar per doc)
    example_template = derive_regex_template([
        Line(tokens=[], y=0, text=r["raw"]) for r in rows[: min(50, len(rows))]
    ])
    print("\nLearned structural regex (no literals):")
    print(example_template)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Extract transactions from PDF statements')
    parser.add_argument('pdf_path', help='Path to the PDF statement')
    parser.add_argument('--draw', action='store_true', help='Export PNG analysis for each page')
    
    args = parser.parse_args()
    
    if args.draw and not DRAWING_AVAILABLE:
        print("Error: --draw flag requires PIL. Install with: pip install Pillow")
        sys.exit(1)
    
    main(args.pdf_path, args.draw)
