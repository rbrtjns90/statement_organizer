"""
Multi-Stage Bank Detection System
----------------------------------
Cascading detection strategy with confidence scoring:
1. Regex patterns (fast, specific)
2. Layout fingerprinting (header positions, font analysis)
3. AI detection (image + text, confidence threshold)
4. Unknown bank handling
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum
import re
import json
import os
from datetime import datetime


class DetectionStage(Enum):
    """Stages in the detection pipeline."""
    REGEX = "regex"
    LAYOUT = "layout"
    AI = "ai"
    UNKNOWN = "unknown"


@dataclass
class DetectionResult:
    """Result from bank detection."""
    bank_name: str
    confidence: float  # 0-100 scale
    stage: DetectionStage
    metadata: Dict[str, Any]
    
    def is_confident(self, threshold: float = 70.0) -> bool:
        """Check if detection meets confidence threshold."""
        return self.confidence >= threshold


class LayoutFingerprinter:
    """Analyzes PDF layout to identify bank statements."""
    
    # Known bank layout signatures
    # These describe distinctive visual/layout patterns.
    # IMPORTANT: header_patterns must use BANK-SPECIFIC markers only. Generic
    # phrases like "Account Summary", "Statement Period", and "Statement" appear
    # on virtually every bank statement and caused widespread misdetection
    # (BofA statements misrouted to Chase/Citibank). Date format alone is too
    # weak to identify a bank, so we rely on brand markers here.
    LAYOUT_SIGNATURES = {
        "Chase": {
            "header_patterns": [r"J\.?P\.? Morgan", r"JPMORGAN CHASE", r"CHASE BANK"],
            "logo_position": "top_left",
            "date_format": r"\d{2}/\d{2}/\d{2}",
            "table_headers": ["Date", "Description", "Amount"],
        },
        "Bank of America": {
            "header_patterns": [r"Bank of America", r"bankofamerica\.com", r"BANK OF AMERICA, N\.A\."],
            "logo_position": "top_center",
            "date_format": r"\d{2}/\d{2}/\d{4}",
        },
        "Citibank": {
            "header_patterns": [r"Citibank", r"CITIBANK, N\.A\.", r"online\.citi\.com"],
            "logo_position": "top_left",
            "date_format": r"\d{2}/\d{2}/\d{4}",
        },
        "Wells Fargo": {
            "header_patterns": [r"Wells Fargo", r"wellsfargo\.com"],
            "logo_position": "top_left",
        },
    }
    
    def analyze(self, pdf_path: str, text: str) -> Optional[DetectionResult]:
        """
        Analyze PDF layout to detect bank.
        
        Args:
            pdf_path: Path to PDF file
            text: Extracted text content
            
        Returns:
            DetectionResult if confident match, None otherwise
        """
        scores = {}
        
        for bank_name, signature in self.LAYOUT_SIGNATURES.items():
            score = 0
            max_score = 0
            
            # Check header patterns
            if "header_patterns" in signature:
                max_score += len(signature["header_patterns"]) * 20
                for pattern in signature["header_patterns"]:
                    if re.search(pattern, text, re.IGNORECASE):
                        score += 20
            
            # Check date format frequency
            if "date_format" in signature:
                max_score += 20
                date_count = len(re.findall(signature["date_format"], text))
                if date_count > 5:  # Multiple dates found
                    score += 20
            
            # Calculate confidence
            if max_score > 0:
                confidence = (score / max_score) * 100
                if confidence > 60:  # Minimum threshold
                    scores[bank_name] = confidence
        
        if scores:
            best_bank = max(scores, key=scores.get)
            return DetectionResult(
                bank_name=best_bank,
                confidence=scores[best_bank],
                stage=DetectionStage.LAYOUT,
                metadata={"layout_score": scores[best_bank]}
            )
        
        return None


class MultiStageBankDetector:
    """Multi-stage bank detection with cascading fallback."""
    
    # Banks that work better with regex than AI
    REGEX_PRIORITY_BANKS = ["Navy Federal", "Chase", "Citibank"]
    
    # Minimum confidence for each stage
    CONFIDENCE_THRESHOLDS = {
        DetectionStage.REGEX: 80.0,
        DetectionStage.LAYOUT: 70.0,
        DetectionStage.AI: 75.0,
    }
    
    def __init__(self):
        """Initialize the multi-stage detector."""
        self.layout_analyzer = LayoutFingerprinter()
        self._detection_history: List[DetectionResult] = []
    
    def detect(self, pdf_path: str, text: str) -> DetectionResult:
        """
        Detect bank using multi-stage cascading strategy.
        
        Stage 1: Regex patterns (fastest, most reliable for known patterns)
        Stage 2: Layout fingerprinting (analyzes structure)
        Stage 3: AI detection (multimodal, most flexible)
        Stage 4: Unknown bank fallback
        
        Args:
            pdf_path: Path to PDF file
            text: Extracted text content
            
        Returns:
            DetectionResult with bank name and confidence
        """
        # Stage 1: Try regex detection
        regex_result = self._detect_with_regex(text, pdf_path)
        if regex_result and regex_result.is_confident(
            self.CONFIDENCE_THRESHOLDS[DetectionStage.REGEX]
        ):
            print(f"📋 Regex detected: {regex_result.bank_name} (confidence: {regex_result.confidence:.0f}%)")
            return regex_result
        
        # Stage 2: Try layout analysis
        layout_result = self.layout_analyzer.analyze(pdf_path, text)
        if layout_result and layout_result.is_confident(
            self.CONFIDENCE_THRESHOLDS[DetectionStage.LAYOUT]
        ):
            print(f"📐 Layout detected: {layout_result.bank_name} (confidence: {layout_result.confidence:.0f}%)")
            return layout_result
        
        # Stage 3: Try AI detection if available
        ai_result = self._detect_with_ai(pdf_path)
        if ai_result and ai_result.is_confident(
            self.CONFIDENCE_THRESHOLDS[DetectionStage.AI]
        ):
            print(f"🤖 AI detected: {ai_result.bank_name} (confidence: {ai_result.confidence:.0f}%)")
            
            # If AI detected unknown bank, log it
            if ai_result.bank_name == "Unknown":
                self._log_unknown_bank(ai_result, pdf_path)
            
            return ai_result
        
        # Stage 4: Unknown bank fallback
        # Combine all results to make best guess
        combined_result = self._combine_results(regex_result, layout_result, ai_result)
        if combined_result:
            print(f"🆕 Unknown bank detected: {combined_result.bank_name} (combined confidence: {combined_result.confidence:.0f}%)")
            self._log_unknown_bank(combined_result, pdf_path)
            return combined_result
        
        # Ultimate fallback
        return DetectionResult(
            bank_name="Unknown",
            confidence=0.0,
            stage=DetectionStage.UNKNOWN,
            metadata={"reason": "All detection methods failed"}
        )
    
    def _detect_with_regex(self, text: str, pdf_path: str) -> Optional[DetectionResult]:
        """Stage 1: Regex pattern matching."""
        from .registry import parser_registry
        
        # Try to get parser from registry
        parser = parser_registry.get_parser(text)
        
        if parser and parser.bank_name:
            # Check if this is a high-confidence regex match
            confidence = 90.0 if parser.bank_name in self.REGEX_PRIORITY_BANKS else 75.0
            
            return DetectionResult(
                bank_name=parser.bank_name,
                confidence=confidence,
                stage=DetectionStage.REGEX,
                metadata={"parser_type": type(parser).__name__}
            )
        
        return None
    
    def _detect_with_ai(self, pdf_path: str) -> Optional[DetectionResult]:
        """Stage 3: AI-based multimodal detection."""
        try:
            from .ai_detector import detect_bank_with_ai
            
            result = detect_bank_with_ai(pdf_path, return_confidence=True)
            
            if result and isinstance(result, dict):
                bank_name = result.get("bank", "Unknown")
                confidence = result.get("confidence", 0)
                
                return DetectionResult(
                    bank_name=bank_name or "Unknown",
                    confidence=float(confidence),
                    stage=DetectionStage.AI,
                    metadata={"ai_backend": "llama_cpp"}
                )
        except Exception as e:
            print(f"⚠️ AI detection failed: {e}")
        
        return None
    
    def _combine_results(
        self,
        regex_result: Optional[DetectionResult],
        layout_result: Optional[DetectionResult],
        ai_result: Optional[DetectionResult]
    ) -> Optional[DetectionResult]:
        """Combine partial results to make best guess."""
        all_results = [r for r in [regex_result, layout_result, ai_result] if r]
        
        if not all_results:
            return None
        
        # Weight by stage reliability
        weights = {
            DetectionStage.REGEX: 1.0,
            DetectionStage.LAYOUT: 0.8,
            DetectionStage.AI: 0.9,
        }
        
        # Score each bank
        bank_scores: Dict[str, float] = {}
        for result in all_results:
            bank = result.bank_name
            if bank == "Unknown":
                continue
            
            weight = weights.get(result.stage, 0.5)
            score = result.confidence * weight
            
            if bank in bank_scores:
                bank_scores[bank] += score
            else:
                bank_scores[bank] = score
        
        if bank_scores:
            best_bank = max(bank_scores, key=bank_scores.get)
            total_confidence = bank_scores[best_bank] / sum(weights.values())
            
            return DetectionResult(
                bank_name=best_bank,
                confidence=min(total_confidence, 65.0),  # Cap at 65% for combined results
                stage=DetectionStage.UNKNOWN,
                metadata={
                    "component_results": [
                        {"stage": r.stage.value, "bank": r.bank_name, "confidence": r.confidence}
                        for r in all_results
                    ]
                }
            )
        
        return None
    
    def _log_unknown_bank(self, result: DetectionResult, pdf_path: str):
        """Log unknown bank detection for future parser development."""
        log_file = "config/unknown_banks.json"
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        # Load existing log
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r') as f:
                    log_data = json.load(f)
            except:
                log_data = {}
        else:
            log_data = {}
        
        bank_name = result.bank_name
        
        # Add entry
        if bank_name not in log_data:
            log_data[bank_name] = {
                "first_seen": datetime.now().isoformat(),
                "count": 0,
                "samples": [],
                "detection_stages": []
            }
        
        log_data[bank_name]["count"] += 1
        log_data[bank_name]["last_seen"] = datetime.now().isoformat()
        
        # Record detection stages used
        if result.metadata.get("component_results"):
            stages = [r["stage"] for r in result.metadata["component_results"]]
            log_data[bank_name]["detection_stages"] = list(set(
                log_data[bank_name].get("detection_stages", []) + stages
            ))
        
        # Keep up to 5 sample paths
        samples = log_data[bank_name]["samples"]
        if len(samples) < 5:
            samples.append({
                "path": pdf_path,
                "confidence": result.confidence,
                "date": datetime.now().isoformat()
            })
        
        # Save log
        with open(log_file, 'w') as f:
            json.dump(log_data, f, indent=2)


# Convenience function
def detect_bank_multi_stage(pdf_path: str, text: str) -> str:
    """
    Detect bank using multi-stage pipeline.
    
    Args:
        pdf_path: Path to PDF file
        text: Extracted text content
        
    Returns:
        Detected bank name
    """
    detector = MultiStageBankDetector()
    result = detector.detect(pdf_path, text)
    return result.bank_name
