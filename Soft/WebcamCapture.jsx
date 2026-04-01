/**
 * frontend/src/components/WebcamCapture.jsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Webcam component that:
 *   1. Streams the user's camera in real-time
 *   2. Overlays the MTCNN bounding box returned by the backend
 *   3. Captures frames (base64 JPEG) for face enrolment or verification
 *   4. Optionally runs a liveness challenge countdown
 *
 * Props:
 *   mode          "enroll" | "verify"
 *   onCapture     (base64ImageString) => void   – called for each captured frame
 *   onComplete    (capturesArray) => void       – called when done capturing
 *   targetCount   number (default 5 for enroll, 1 for verify)
 *   showLiveness  bool – show blink/challenge overlay
 */

import { useRef, useState, useEffect, useCallback } from "react";
import { Camera, CheckCircle, AlertTriangle, RefreshCw, Scan, Zap } from "lucide-react";

const CAPTURE_INTERVAL_MS = 600;    // ms between auto-captures in enroll mode
const JPEG_QUALITY        = 0.92;   // canvas toDataURL quality

export default function WebcamCapture({
  mode = "verify",
  onCapture,
  onComplete,
  targetCount = mode === "enroll" ? 5 : 1,
  showLiveness = false,
}) {
  const videoRef    = useRef(null);
  const canvasRef   = useRef(null);
  const streamRef   = useRef(null);
  const intervalRef = useRef(null);

  const [status,       setStatus]       = useState("idle");     // idle|streaming|capturing|done|error
  const [captures,     setCaptures]     = useState([]);
  const [bboxes,       setBboxes]       = useState([]);          // [{x1,y1,x2,y2,prob}] from backend
  const [error,        setError]        = useState(null);
  const [liveness,     setLiveness]     = useState(null);        // challenge string
  const [countdown,    setCountdown]    = useState(3);

  // ── Start camera ─────────────────────────────────────────────────────────
  const startCamera = useCallback(async () => {
    setError(null);
    setStatus("idle");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setStatus("streaming");

      if (showLiveness) {
        setLiveness(["blink twice", "turn left", "smile"][Math.floor(Math.random() * 3)]);
      }
    } catch (err) {
      setError("Camera access denied. Please allow camera permissions.");
      setStatus("error");
    }
  }, [showLiveness]);

  // ── Stop camera ───────────────────────────────────────────────────────────
  const stopCamera = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  useEffect(() => {
    startCamera();
    return () => stopCamera();
  }, [startCamera, stopCamera]);

  // ── Capture a single frame ────────────────────────────────────────────────
  const captureFrame = useCallback(() => {
    const video  = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || video.readyState < 2) return null;

    canvas.width  = video.videoWidth  || 640;
    canvas.height = video.videoHeight || 480;
    const ctx = canvas.getContext("2d");

    // Mirror the canvas to match the mirrored video preview
    ctx.save();
    ctx.scale(-1, 1);
    ctx.drawImage(video, -canvas.width, 0, canvas.width, canvas.height);
    ctx.restore();

    return canvas.toDataURL("image/jpeg", JPEG_QUALITY);
  }, []);

  // ── Auto-capture loop for enrolment ──────────────────────────────────────
  const startAutoCapture = useCallback(() => {
    if (status !== "streaming") return;
    setStatus("capturing");

    intervalRef.current = setInterval(() => {
      const frame = captureFrame();
      if (!frame) return;

      setCaptures(prev => {
        const next = [...prev, frame];
        if (onCapture) onCapture(frame);
        if (next.length >= targetCount) {
          clearInterval(intervalRef.current);
          setStatus("done");
          if (onComplete) onComplete(next);
        }
        return next;
      });
    }, CAPTURE_INTERVAL_MS);
  }, [status, captureFrame, onCapture, onComplete, targetCount]);

  // ── Single-shot capture for verification ─────────────────────────────────
  const captureOnce = useCallback(() => {
    const frame = captureFrame();
    if (!frame) return;
    setCaptures([frame]);
    setStatus("done");
    if (onCapture) onCapture(frame);
    if (onComplete) onComplete([frame]);
  }, [captureFrame, onCapture, onComplete]);

  // ── Restart ───────────────────────────────────────────────────────────────
  const restart = () => {
    stopCamera();
    setCaptures([]);
    setBboxes([]);
    setStatus("idle");
    setTimeout(startCamera, 300);
  };

  const progress = Math.round((captures.length / targetCount) * 100);

  return (
    <div className="flex flex-col items-center gap-4 w-full">

      {/* Video + overlay */}
      <div className="relative rounded-2xl overflow-hidden bg-slate-950 w-full max-w-xs aspect-[4/3] border border-slate-700/50"
           style={{ boxShadow: "0 0 40px rgba(16,185,129,0.08)" }}>

        {/* Mirrored video */}
        <video ref={videoRef} muted playsInline
               className="w-full h-full object-cover"
               style={{ transform: "scaleX(-1)" }} />

        {/* Canvas (hidden – used for capture only) */}
        <canvas ref={canvasRef} className="hidden" />

        {/* Corner brackets */}
        {["top-2 left-2", "top-2 right-2", "bottom-2 left-2", "bottom-2 right-2"].map((pos, i) => (
          <div key={i} className={`absolute ${pos} w-6 h-6 border-emerald-400 pointer-events-none`}
               style={{
                 borderTopWidth:    i < 2  ? 2 : 0,
                 borderBottomWidth: i >= 2 ? 2 : 0,
                 borderLeftWidth:   i % 2 === 0 ? 2 : 0,
                 borderRightWidth:  i % 2 === 1 ? 2 : 0,
               }} />
        ))}

        {/* MTCNN Bounding Box overlay */}
        {bboxes.map((box, i) => (
          <div key={i} className="absolute border-2 border-emerald-400 rounded pointer-events-none"
               style={{
                 left:   `${(box.x1 / 640) * 100}%`,
                 top:    `${(box.y1 / 480) * 100}%`,
                 width:  `${((box.x2 - box.x1) / 640) * 100}%`,
                 height: `${((box.y2 - box.y1) / 480) * 100}%`,
               }}>
            <span className="absolute -top-5 left-0 text-xs text-emerald-400 bg-slate-900/80 px-1 rounded">
              {Math.round((box.prob || 0) * 100)}%
            </span>
          </div>
        ))}

        {/* Scan line animation while streaming */}
        {status === "streaming" && (
          <div className="absolute inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-emerald-400 to-transparent opacity-70 pointer-events-none"
               style={{ animation: "scanY 2s ease-in-out infinite", top: 0 }} />
        )}

        {/* Done overlay */}
        {status === "done" && (
          <div className="absolute inset-0 bg-emerald-500/20 flex items-center justify-center">
            <div className="bg-slate-900/90 rounded-2xl p-4 flex flex-col items-center gap-2">
              <CheckCircle size={32} className="text-emerald-400" />
              <p className="text-white text-sm font-semibold">Captured!</p>
            </div>
          </div>
        )}

        {/* Error overlay */}
        {status === "error" && (
          <div className="absolute inset-0 bg-red-500/10 flex items-center justify-center p-4">
            <div className="text-center">
              <AlertTriangle size={24} className="text-red-400 mx-auto mb-2" />
              <p className="text-red-300 text-xs">{error}</p>
            </div>
          </div>
        )}

        {/* Liveness challenge badge */}
        {liveness && status === "streaming" && (
          <div className="absolute bottom-3 left-1/2 -translate-x-1/2 px-3 py-1.5 bg-amber-500/90 rounded-full text-black text-xs font-bold uppercase tracking-wide">
            ⚡ {liveness}
          </div>
        )}
      </div>

      {/* Progress bar (enroll mode) */}
      {mode === "enroll" && (
        <div className="w-full max-w-xs">
          <div className="flex justify-between text-xs text-slate-400 mb-1">
            <span>Captures</span>
            <span>{captures.length} / {targetCount}</span>
          </div>
          <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
            <div className="h-full bg-emerald-400 rounded-full transition-all duration-300"
                 style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-3">
        {status === "streaming" && mode === "verify" && (
          <button onClick={captureOnce}
                  className="flex items-center gap-2 px-5 py-2.5 bg-emerald-500 hover:bg-emerald-400 text-black font-bold rounded-xl text-sm transition-all active:scale-95">
            <Scan size={16} /> Verify Face
          </button>
        )}

        {status === "streaming" && mode === "enroll" && (
          <button onClick={startAutoCapture}
                  className="flex items-center gap-2 px-5 py-2.5 bg-blue-500 hover:bg-blue-400 text-white font-bold rounded-xl text-sm transition-all active:scale-95">
            <Camera size={16} /> Start Enrolment
          </button>
        )}

        {status === "capturing" && (
          <div className="flex items-center gap-2 px-5 py-2.5 bg-slate-800 rounded-xl text-sm text-emerald-400">
            <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            Capturing... {captures.length}/{targetCount}
          </div>
        )}

        {(status === "done" || status === "error") && (
          <button onClick={restart}
                  className="flex items-center gap-2 px-5 py-2.5 bg-slate-800 hover:bg-slate-700 text-white rounded-xl text-sm transition-all">
            <RefreshCw size={14} /> Retake
          </button>
        )}
      </div>

      <style>{`
        @keyframes scanY {
          0%   { top: 10%;   opacity: 1; }
          50%  { top: 85%;   opacity: 0.7; }
          100% { top: 10%;   opacity: 1; }
        }
      `}</style>
    </div>
  );
}
