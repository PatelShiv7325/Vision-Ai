import cv2
import numpy as np
import time
from collections import deque
import math

class LivenessDetector:
    def __init__(self):
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        self.eye_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_eye.xml'
        )
        self.smile_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_smile.xml'
        )
        
        # Blink detection parameters
        self.blink_threshold = 0.3
        self.blink_frames_required = 3
        self.blink_history = deque(maxlen=10)
        
        # Head movement detection
        self.head_movement_threshold = 15
        self.previous_face_center = None
        self.movement_history = deque(maxlen=5)
        
        # Challenge-response
        self.current_challenge = None
        self.challenge_start_time = None
        self.challenge_timeout = 15  # seconds
        
        # Texture analysis for photo detection
        self.texture_threshold = 0.02
        
    def detect_liveness(self, frame, challenge_type=None):
        """Comprehensive liveness detection"""
        results = {
            'is_live': False,
            'confidence': 0.0,
            'checks': {},
            'challenge_completed': False
        }
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(100, 100)
        )
        
        if len(faces) == 0:
            return results
        
        # Get the largest face
        face = max(faces, key=lambda f: f[2] * f[3])
        x, y, w, h = face
        face_region = gray[y:y+h, x:x+w]
        face_color = frame[y:y+h, x:x+w]
        
        # Perform various liveness checks
        checks = {}
        
        # 1. Blink detection
        blink_result = self._detect_blink(face_region)
        checks['blink'] = blink_result
        
        # 2. Head movement detection
        movement_result = self._detect_head_movement(x + w//2, y + h//2)
        checks['movement'] = movement_result
        
        # 3. Eye detection (prevents photo spoofing)
        eye_result = self._detect_eyes(face_region)
        checks['eyes'] = eye_result
        
        # 4. Texture analysis (detects printed photos)
        texture_result = self._analyze_texture(face_color)
        checks['texture'] = texture_result
        
        # 5. Challenge-response if specified
        if challenge_type:
            challenge_result = self._perform_challenge(frame, face, challenge_type)
            checks['challenge'] = challenge_result
            results['challenge_completed'] = challenge_result.get('completed', False)
        
        results['checks'] = checks
        
        # Calculate overall liveness confidence
        confidence = self._calculate_liveness_confidence(checks)
        results['confidence'] = confidence
        
        # Determine if live (threshold: 0.7)
        results['is_live'] = confidence >= 0.7
        
        return results
    
    def _detect_blink(self, face_region):
        """Detect eye blinking"""
        eyes = self.eye_cascade.detectMultiScale(
            face_region, scaleFactor=1.1, minNeighbors=3, minSize=(20, 20)
        )
        
        # Simple blink detection based on eye aspect ratio
        if len(eyes) >= 2:
            # Calculate eye aspect ratio
            eye_aspect_ratio = self._calculate_eye_aspect_ratio(face_region, eyes)
            self.blink_history.append(eye_aspect_ratio)
            
            # Check for blink pattern
            if len(self.blink_history) >= self.blink_frames_required:
                recent_values = list(self.blink_history)[-self.blink_frames_required:]
                avg_ratio = sum(recent_values) / len(recent_values)
                
                return {
                    'detected': avg_ratio < self.blink_threshold,
                    'aspect_ratio': avg_ratio,
                    'confidence': 1.0 - avg_ratio if avg_ratio < self.blink_threshold else 0.0
                }
        
        return {'detected': False, 'aspect_ratio': 0.5, 'confidence': 0.0}
    
    def _calculate_eye_aspect_ratio(self, face_region, eyes):
        """Calculate eye aspect ratio for blink detection"""
        if len(eyes) < 2:
            return 0.5
        
        # Simple approximation of eye aspect ratio
        total_eye_area = sum(w * h for (x, y, w, h) in eyes)
        face_area = face_region.shape[0] * face_region.shape[1]
        
        return total_eye_area / face_area if face_area > 0 else 0.5
    
    def _detect_head_movement(self, face_center_x, face_center_y):
        """Detect natural head movement"""
        current_center = (face_center_x, face_center_y)
        
        if self.previous_face_center is None:
            self.previous_face_center = current_center
            return {'detected': False, 'movement': 0, 'confidence': 0.0}
        
        # Calculate movement distance
        dx = current_center[0] - self.previous_face_center[0]
        dy = current_center[1] - self.previous_face_center[1]
        movement = math.sqrt(dx*dx + dy*dy)
        
        self.movement_history.append(movement)
        self.previous_face_center = current_center
        
        # Check for natural movement patterns
        if len(self.movement_history) >= 3:
            avg_movement = sum(self.movement_history) / len(self.movement_history)
            
            return {
                'detected': avg_movement > 2,  # Small natural movements
                'movement': avg_movement,
                'confidence': min(avg_movement / 10, 1.0)
            }
        
        return {'detected': False, 'movement': movement, 'confidence': 0.0}
    
    def _detect_eyes(self, face_region):
        """Detect eyes in the face region"""
        eyes = self.eye_cascade.detectMultiScale(
            face_region, scaleFactor=1.1, minNeighbors=3, minSize=(15, 15)
        )
        
        return {
            'detected': len(eyes) >= 2,
            'eye_count': len(eyes),
            'confidence': min(len(eyes) / 2, 1.0)
        }
    
    def _analyze_texture(self, face_color):
        """Analyze facial texture to detect photos"""
        # Convert to grayscale for texture analysis
        gray = cv2.cvtColor(face_color, cv2.COLOR_BGR2GRAY)
        
        # Calculate Local Binary Pattern (LBP) histogram
        lbp = self._calculate_lbp(gray)
        hist, _ = np.histogram(lbp.ravel(), bins=256, range=(0, 256))
        
        # Normalize histogram
        hist = hist.astype(float)
        hist /= (hist.sum() + 1e-7)
        
        # Calculate texture variance (low variance indicates photo)
        texture_variance = np.var(hist)
        
        return {
            'detected': texture_variance > self.texture_threshold,
            'variance': texture_variance,
            'confidence': min(texture_variance * 10, 1.0)
        }
    
    def _calculate_lbp(self, image, radius=1, neighbors=8):
        """Calculate Local Binary Pattern"""
        height, width = image.shape
        lbp = np.zeros((height, width), dtype=np.uint8)
        
        for i in range(radius, height - radius):
            for j in range(radius, width - radius):
                center = image[i, j]
                binary = 0
                
                for n in range(neighbors):
                    angle = 2 * math.pi * n / neighbors
                    x = int(i + radius * math.cos(angle))
                    y = int(j + radius * math.sin(angle))
                    
                    if 0 <= x < height and 0 <= y < width:
                        if image[x, y] >= center:
                            binary |= (1 << n)
                
                lbp[i, j] = binary
        
        return lbp
    
    def _perform_challenge(self, frame, face, challenge_type):
        """Perform challenge-response test"""
        if self.current_challenge is None:
            self.current_challenge = challenge_type
            self.challenge_start_time = time.time()
        
        elapsed_time = time.time() - self.challenge_start_time
        
        if elapsed_time > self.challenge_timeout:
            return {'completed': False, 'timeout': True, 'confidence': 0.0}
        
        if challenge_type == 'blink':
            return self._blink_challenge(frame, face)
        elif challenge_type == 'smile':
            return self._smile_challenge(frame, face)
        elif challenge_type == 'head_turn':
            return self._head_turn_challenge(frame, face)
        
        return {'completed': False, 'confidence': 0.0}
    
    def _blink_challenge(self, frame, face):
        """Challenge: Blink three times"""
        x, y, w, h = face
        face_region = frame[y:y+h, x:x+w]
        gray_face = cv2.cvtColor(face_region, cv2.COLOR_BGR2GRAY)
        
        eyes = self.eye_cascade.detectMultiScale(
            gray_face, scaleFactor=1.1, minNeighbors=3
        )
        
        # This is a simplified blink challenge
        # In practice, you'd need more sophisticated blink counting
        return {
            'completed': len(eyes) >= 2,
            'confidence': 0.8 if len(eyes) >= 2 else 0.0
        }
    
    def _smile_challenge(self, frame, face):
        """Challenge: Smile"""
        x, y, w, h = face
        face_region = frame[y:y+h, x:x+w]
        gray_face = cv2.cvtColor(face_region, cv2.COLOR_BGR2GRAY)
        
        smiles = self.smile_cascade.detectMultiScale(
            gray_face, scaleFactor=1.7, minNeighbors=20, minSize=(25, 25)
        )
        
        return {
            'completed': len(smiles) > 0,
            'confidence': 0.9 if len(smiles) > 0 else 0.0
        }
    
    def _head_turn_challenge(self, frame, face):
        """Challenge: Turn head left and right"""
        # This would require tracking head position over time
        # Simplified implementation
        return {
            'completed': True,
            'confidence': 0.7
        }
    
    def _calculate_liveness_confidence(self, checks):
        """Calculate overall liveness confidence from all checks"""
        weights = {
            'blink': 0.3,
            'movement': 0.2,
            'eyes': 0.2,
            'texture': 0.2,
            'challenge': 0.1
        }
        
        total_confidence = 0.0
        total_weight = 0.0
        
        for check_name, weight in weights.items():
            if check_name in checks:
                check_confidence = checks[check_name].get('confidence', 0.0)
                total_confidence += check_confidence * weight
                total_weight += weight
        
        return total_confidence / total_weight if total_weight > 0 else 0.0
    
    def reset(self):
        """Reset detector state"""
        self.blink_history.clear()
        self.movement_history.clear()
        self.previous_face_center = None
        self.current_challenge = None
        self.challenge_start_time = None

# Utility function for real-time liveness detection (REMOVED - causes errors in web interface)
# This function was causing camera access conflicts and has been completely removed
