"""Object detector: red paper obstacles + yellow projected balls (OpenCV HSV)."""

from dataclasses import dataclass, field

import cv2
import numpy as np

# Red paper HSV ranges — red wraps around 180° in HSV
RED_LOWER1 = np.array([0, 100, 100], dtype=np.uint8)
RED_UPPER1 = np.array([10, 255, 255], dtype=np.uint8)
RED_LOWER2 = np.array([160, 100, 100], dtype=np.uint8)
RED_UPPER2 = np.array([180, 255, 255], dtype=np.uint8)

# Yellow ball HSV range
YELLOW_LOWER = np.array([18, 100, 100], dtype=np.uint8)
YELLOW_UPPER = np.array([38, 255, 255], dtype=np.uint8)

MIN_PAPER_AREA = 2000  # px², filters noise
MIN_DEFECT_DEPTH = 35  # px — deeper concavity = two merged papers, split them
MIN_BALL_RADIUS = 5  # px
MAX_BALL_RADIUS = 60  # px


@dataclass
class Obstacle:
    id: str
    cx: float
    cy: float
    w: float
    h: float
    angle: float
    vertices: list[list[float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cx": round(self.cx, 1),
            "cy": round(self.cy, 1),
            "w": round(self.w, 1),
            "h": round(self.h, 1),
            "angle": round(self.angle, 2),
            "vertices": [[round(x, 1), round(y, 1)] for x, y in self.vertices],
        }


@dataclass
class Ball:
    id: str
    x: float
    y: float
    r: float

    def to_dict(self) -> dict:
        return {"id": self.id, "x": round(self.x), "y": round(self.y), "r": round(self.r)}


class Detector:
    """
    Detects red paper obstacles and yellow balls from a camera frame.
    Uses OpenCV HSV color segmentation (fast, reliable for known colors).
    """

    def __init__(self):
        self._morph_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        self._small_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self._screen_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 20))

    def _build_hsv_mask(
        self,
        hsv: np.ndarray,
        lower1: np.ndarray,
        upper1: np.ndarray,
        lower2: np.ndarray | None = None,
        upper2: np.ndarray | None = None,
    ) -> np.ndarray:
        mask = cv2.inRange(hsv, lower1, upper1)
        if lower2 is not None and upper2 is not None:
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv, lower2, upper2))
        # Remove small noise blobs
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._morph_kernel)
        # Fill small holes
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._morph_kernel)
        return mask

    # ── Projected screen detection ────────────────────────────────────────────

    @staticmethod
    def _sort_corners(pts: np.ndarray) -> np.ndarray:
        """
        Return 4 points sorted as [TL, TR, BR, BL].

        Uses angle from centroid so it stays correct when the camera
        is tilted or offset — the x+y/y-x heuristic breaks in that case.

        In image coordinates (y increases downward):
          TL → arctan2(neg, neg) ≈ -135°
          TR → arctan2(neg, pos) ≈  -45°
          BR → arctan2(pos, pos) ≈  +45°
          BL → arctan2(pos, neg) ≈ +135°
        Ascending arctan2 order → [TL, TR, BR, BL].
        """
        cx, cy = pts.mean(axis=0)
        angles = np.arctan2(pts[:, 1] - cy, pts[:, 0] - cx)
        order = np.argsort(angles)  # TL(-135°) TR(-45°) BR(+45°) BL(+135°)
        return pts[order].astype(np.float32)

    def detect_screen_corners(self, frame: np.ndarray) -> np.ndarray | None:
        """
        Find the projected screen rectangle in the camera frame.

        Works with BOTH a bright-filled background AND a thin bright border
        on a dark background:
          1. OTSU threshold → all bright pixels (border, balls, etc.)
          2. Small open to kill isolated specks
          3. Convex hull of ALL remaining bright pixels — their outer hull
             is always the screen boundary regardless of interior content
          4. approxPolyDP → 4 corners

        Returns float32 array [TL, TR, BR, BL] or None.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        _, bright = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Remove tiny noise blobs (camera grain, ambient reflections)
        # Keep kernel small so the 6 px white border is not eroded
        open_k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, open_k)

        # Collect all surviving bright pixel coordinates
        ys, xs = np.where(bright > 0)
        if len(xs) < 200:  # too few bright pixels → nothing detected
            return None

        pts_xy = np.column_stack([xs, ys]).reshape(-1, 1, 2).astype(np.int32)

        # Convex hull of all bright pixels = outer boundary of projected content
        hull = cv2.convexHull(pts_xy)

        # Must cover at least 5 % of frame
        if cv2.contourArea(hull) < frame.shape[0] * frame.shape[1] * 0.05:
            return None

        # Approximate convex hull to a quadrilateral
        peri = cv2.arcLength(hull, True)
        approx = None
        for eps in [0.02, 0.04, 0.06, 0.10, 0.15]:
            candidate = cv2.approxPolyDP(hull, eps * peri, True)
            if len(candidate) == 4:
                approx = candidate
                break

        if approx is None:
            return None

        pts = approx.reshape(4, 2).astype(np.float32)
        return self._sort_corners(pts)

    def build_screen_mask(self, frame: np.ndarray, corners: np.ndarray) -> np.ndarray:
        """Return a binary mask (uint8) that is 255 inside the projected screen polygon."""
        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        cv2.fillPoly(mask, [corners.astype(np.int32)], 255)
        return mask

    # ── Concave contour splitting ─────────────────────────────────────────────

    def _split_concave(
        self, cnt: np.ndarray, frame_shape: tuple, depth: int = 0
    ) -> list[np.ndarray]:
        """
        Recursively split a non-convex contour at its deepest convexity defect.

        Strategy: rather than slicing the point array (which gives only half the
        perimeter and breaks minAreaRect), we draw the merged region into a
        temporary mask, cut it with a line through the defect point, and
        re-extract proper closed contours from each piece.  Each resulting
        contour has its full perimeter → minAreaRect is accurate.

        Returns a list of convex sub-contours, one per detected paper.
        """
        if depth > 3 or len(cnt) < 6:
            return [cnt]

        if cv2.isContourConvex(cnt):
            return [cnt]

        hull_idx = cv2.convexHull(cnt, returnPoints=False)
        if hull_idx is None or len(hull_idx) < 3:
            return [cnt]

        try:
            defects = cv2.convexityDefects(cnt, hull_idx)
        except cv2.error:
            return [cnt]

        if defects is None:
            return [cnt]

        # depth field from OpenCV is fixed-point ×256
        pixel_depths = defects[:, 0, 3] / 256.0
        best_i = int(np.argmax(pixel_depths))

        if pixel_depths[best_i] < MIN_DEFECT_DEPTH:
            return [cnt]  # slight concavity = noise/rounding, not two merged papers

        s, e, f, _ = defects[best_i, 0]
        far_pt = cnt[f][0].astype(float)  # the V-notch point
        start_pt = cnt[s][0].astype(float)  # hull edge start
        end_pt = cnt[e][0].astype(float)  # hull edge end

        # Cut direction: perpendicular to the hull edge that spans the defect
        edge = end_pt - start_pt
        edge_len = float(np.linalg.norm(edge))
        if edge_len < 1.0:
            return [cnt]
        perp = np.array([-edge[1], edge[0]]) / edge_len

        # ── Render contour → temporary mask ──────────────────────────────────
        h, w = frame_shape[:2]
        tmp = np.zeros((h, w), dtype=np.uint8)
        cv2.drawContours(tmp, [cnt], 0, 255, cv2.FILLED)

        # Draw a thick black line through the notch point to split the mask
        ext = float(max(h, w))
        pt1 = tuple((far_pt + perp * ext).astype(int))
        pt2 = tuple((far_pt - perp * ext).astype(int))
        cv2.line(tmp, pt1, pt2, 0, 5)  # 5 px ensures a clean gap

        # ── Re-extract sub-contours from each piece ───────────────────────────
        sub_cnts, _ = cv2.findContours(tmp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        result: list[np.ndarray] = []
        for sc in sub_cnts:
            if len(sc) < 4 or cv2.contourArea(sc) < MIN_PAPER_AREA // 4:
                continue
            result.extend(self._split_concave(sc, frame_shape, depth + 1))

        return result if result else [cnt]

    # ── Red paper detection ───────────────────────────────────────────────────

    def detect_red_papers(
        self, frame: np.ndarray, roi_mask: np.ndarray | None = None
    ) -> list[Obstacle]:
        """
        Find red paper sheets as oriented bounding-box obstacles.
        Handles V-shaped merged contours by splitting at convexity defects.

        roi_mask: uint8 mask (255 = search here, 0 = ignore).
                  Pass the result of build_screen_mask() to restrict
                  detection to inside the projected screen area.
        """
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = self._build_hsv_mask(hsv, RED_LOWER1, RED_UPPER1, RED_LOWER2, RED_UPPER2)

        # Restrict to projected screen area when ROI is available
        if roi_mask is not None:
            mask = cv2.bitwise_and(mask, roi_mask)

        raw_contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        obstacles: list[Obstacle] = []
        paper_num = 0

        for raw_cnt in raw_contours:
            if cv2.contourArea(raw_cnt) < MIN_PAPER_AREA:
                continue

            # Split merged/concave contours before fitting rectangles
            sub_contours = self._split_concave(raw_cnt, frame.shape)

            for sub_cnt in sub_contours:
                if cv2.contourArea(sub_cnt) < MIN_PAPER_AREA // 3:
                    continue

                rect = cv2.minAreaRect(sub_cnt)
                box = cv2.boxPoints(rect)

                (cx, cy), (w, h), angle = rect
                if w < h:
                    w, h = h, w
                    angle += 90

                obstacles.append(
                    Obstacle(
                        id=f"paper_{paper_num}",
                        cx=float(cx),
                        cy=float(cy),
                        w=float(w),
                        h=float(h),
                        angle=float(angle),
                        vertices=box.tolist(),
                    )
                )
                paper_num += 1

        return obstacles

    def detect_yellow_balls(self, frame: np.ndarray) -> list[Ball]:
        """
        Detect projected yellow balls via HSV + Hough circles.
        Used for calibration verification.
        """
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = self._build_hsv_mask(hsv, YELLOW_LOWER, YELLOW_UPPER)

        blurred = cv2.GaussianBlur(mask, (9, 9), 2)
        circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=25,
            param1=50,
            param2=25,
            minRadius=MIN_BALL_RADIUS,
            maxRadius=MAX_BALL_RADIUS,
        )

        balls: list[Ball] = []
        if circles is not None:
            for idx, (x, y, r) in enumerate(np.round(circles[0]).astype(int)):
                balls.append(Ball(id=f"ball_{idx}", x=float(x), y=float(y), r=float(r)))

        return balls

    def draw_debug_overlay(
        self,
        frame: np.ndarray,
        obstacles: list[Obstacle],
        screen_corners: np.ndarray | None = None,
        balls: list[Ball] = None,
    ) -> np.ndarray:
        """
        Render detected obstacles, split markers, and balls onto the frame.
        Blue quad  = detected projected screen boundary.
        Green box  = detected paper (good).
        Orange X   = convexity-defect split point (visible when papers were merged).
        """
        out = frame.copy()

        # Draw projected screen boundary
        if screen_corners is not None:
            pts = screen_corners.astype(np.int32)
            cv2.polylines(out, [pts], isClosed=True, color=(255, 80, 0), thickness=3)
            for i, (x, y) in enumerate(pts):
                cv2.circle(out, (int(x), int(y)), 8, (255, 80, 0), -1)
                cv2.putText(
                    out,
                    str(i + 1),
                    (int(x) + 10, int(y) - 5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 80, 0),
                    2,
                )

        # Draw each paper's oriented bounding box
        for obs in obstacles:
            pts = np.array(obs.vertices, dtype=np.int32)
            cv2.drawContours(out, [pts], 0, (0, 220, 0), 2)
            cx, cy = int(obs.cx), int(obs.cy)
            cv2.circle(out, (cx, cy), 5, (255, 200, 0), -1)  # centroid dot
            label = f"{obs.id}  {obs.w:.0f}x{obs.h:.0f}  {obs.angle:.1f}deg"
            cv2.putText(
                out, label, (cx + 7, cy - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 0), 1
            )

        # Show convexity defects on raw mask contours (debug only)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = self._build_hsv_mask(hsv, RED_LOWER1, RED_UPPER1, RED_LOWER2, RED_UPPER2)
        raw_cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for raw_cnt in raw_cnts:
            if cv2.contourArea(raw_cnt) < MIN_PAPER_AREA:
                continue
            if cv2.isContourConvex(raw_cnt):
                continue
            hull_idx = cv2.convexHull(raw_cnt, returnPoints=False)
            if hull_idx is None or len(hull_idx) < 3:
                continue
            try:
                defects = cv2.convexityDefects(raw_cnt, hull_idx)
            except cv2.error:
                continue
            if defects is None:
                continue
            for d in defects:
                s, e, f, depth_fp = d[0]
                depth_px = depth_fp / 256.0
                if depth_px < MIN_DEFECT_DEPTH:
                    continue
                fx, fy = raw_cnt[f][0]
                # Draw an orange X at the split point
                r = 7
                cv2.line(out, (fx - r, fy - r), (fx + r, fy + r), (0, 140, 255), 2)
                cv2.line(out, (fx + r, fy - r), (fx - r, fy + r), (0, 140, 255), 2)
                cv2.putText(
                    out,
                    f"split {depth_px:.0f}px",
                    (fx + 9, fy + 4),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.38,
                    (0, 140, 255),
                    1,
                )

        if balls:
            for ball in balls:
                cv2.circle(out, (int(ball.x), int(ball.y)), int(ball.r), (0, 255, 255), 2)

        # HUD: count
        cv2.rectangle(out, (0, 0), (280, 28), (0, 0, 0), -1)
        cv2.putText(
            out,
            f"papers: {len(obstacles)}",
            (6, 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (200, 255, 200),
            1,
        )

        return out
