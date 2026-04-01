/**
 * frontend/src/components/BiometricLogin.jsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Full biometric login component integrating:
 *   • Live webcam capture (WebcamCapture)
 *   • POST /api/auth/face/verify  → face_token
 *   • PIN keypad → POST /api/auth/pin/verify → access token
 *   • SuperDoctor emergency bypass modes
 *
 * Props:
 *   userId       string   – pre-filled user ID (from user selection screen)
 *   isSuperDoctor bool    – show bypass tab
 *   onSuccess    fn(user) – called after full auth
 *   onCancel     fn()
 */

import { useState, useCallback } from "react";
import {
  Shield, Fingerprint, AlertCircle, CheckCircle, Zap,
  Phone, Hash, Camera, X, RefreshCw,
} from "lucide-react";
import WebcamCapture from "./WebcamCapture";
import { useAuth } from "../hooks/useAuth";

const STEPS = {
  FACE:    "face",
  PIN:     "pin",
  BYPASS:  "bypass",
  SUCCESS: "success",
};

export default function BiometricLogin({ userId, isSuperDoctor = false, onSuccess, onCancel }) {
  const { faceVerify, pinVerify, emergencyLookup, isLoading } = useAuth();

  const [step,        setStep]        = useState(STEPS.FACE);
  const [faceToken,   setFaceToken]   = useState(null);
  const [similarity,  setSimilarity]  = useState(null);
  const [pin,         setPin]         = useState("");
  const [error,       setError]       = useState(null);
  const [bypassType,  setBypassType]  = useState("patient_id");
  const [bypassQuery, setBypassQuery] = useState("");

  // ── Face captured callback ────────────────────────────────────────────────
  const handleFaceCapture = useCallback(async (base64Image) => {
    setError(null);
    const res = await faceVerify(userId, base64Image);

    if (res.success) {
      setFaceToken(res.face_token);
      setSimilarity(res.similarity);
      setStep(STEPS.PIN);
    } else {
      setError(res.message || "Face not recognised.");
    }
  }, [userId, faceVerify]);

  // ── PIN digit handler ─────────────────────────────────────────────────────
  const handlePinDigit = useCallback(async (digit) => {
    const next = pin + digit;
    setPin(next);

    if (next.length === 4) {
      setError(null);
      const res = await pinVerify(faceToken, next);

      if (res.success) {
        setStep(STEPS.SUCCESS);
        setTimeout(() => onSuccess(res.user), 600);
      } else {
        setError(res.message || "Incorrect PIN.");
        setPin("");
      }
    }
  }, [pin, faceToken, pinVerify, onSuccess]);

  // ── Emergency bypass ──────────────────────────────────────────────────────
  const handleBypass = useCallback(async () => {
    if (!bypassQuery.trim()) {
      setError("Enter a patient ID or phone number.");
      return;
    }
    setError(null);
    const res = await emergencyLookup(bypassType, bypassQuery.trim());

    if (res.success) {
      setStep(STEPS.SUCCESS);
      setTimeout(() => onSuccess(res.patient), 400);
    } else {
      setError(res.message || "Patient not found.");
    }
  }, [bypassType, bypassQuery, emergencyLookup, onSuccess]);

  const reset = () => {
    setStep(STEPS.FACE);
    setFaceToken(null);
    setSimilarity(null);
    setPin("");
    setError(null);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/85 backdrop-blur-xl">
      <div
        className="relative w-full max-w-md bg-slate-900/95 border border-slate-700/60 rounded-3xl p-8 shadow-2xl"
        style={{ boxShadow: "0 0 80px rgba(16,185,129,0.08), 0 0 0 1px rgba(255,255,255,0.04)" }}
      >
        {/* Close */}
        <button onClick={onCancel}
                className="absolute top-4 right-4 p-2 hover:bg-slate-800 rounded-xl transition-colors text-slate-500 hover:text-white">
          <X size={16} />
        </button>

        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="w-11 h-11 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center">
            <Shield size={20} className="text-emerald-400" />
          </div>
          <div>
            <h2 className="text-white font-bold text-xl">Identity Verification</h2>
            <p className="text-slate-400 text-xs">Biometric 2-Factor Authentication</p>
          </div>
        </div>

        {/* Step tabs (SuperDoctor only) */}
        {isSuperDoctor && step !== STEPS.SUCCESS && (
          <div className="flex gap-1.5 mb-6 p-1 bg-slate-800/60 rounded-xl">
            {[
              { id: STEPS.FACE,   label: "Face ID",     icon: <Camera size={12}/> },
              { id: STEPS.BYPASS, label: "Emergency",   icon: <Zap size={12}/> },
            ].map(t => (
              <button key={t.id} onClick={() => { setStep(t.id); setError(null); setPin(""); }}
                      className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-medium transition-all
                        ${step === t.id
                          ? t.id === STEPS.BYPASS
                            ? "bg-amber-500/20 text-amber-400 border border-amber-500/30"
                            : "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                          : "text-slate-500 hover:text-slate-300"}`}>
                {t.icon} {t.label}
              </button>
            ))}
          </div>
        )}

        {/* ── STEP: FACE ──────────────────────────────────────────────────── */}
        {step === STEPS.FACE && (
          <div className="flex flex-col items-center gap-5">
            <WebcamCapture
              mode="verify"
              onComplete={([frame]) => handleFaceCapture(frame)}
            />
            {isLoading && (
              <div className="flex items-center gap-2 text-emerald-400 text-sm">
                <div className="w-3 h-3 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin" />
                Verifying identity...
              </div>
            )}
            {error && <ErrorBanner message={error} onRetry={reset} />}
          </div>
        )}

        {/* ── STEP: PIN ───────────────────────────────────────────────────── */}
        {step === STEPS.PIN && (
          <div className="flex flex-col items-center gap-6">
            {similarity !== null && (
              <div className="flex items-center gap-2 px-3 py-2 bg-emerald-500/10 border border-emerald-500/20 rounded-xl w-full">
                <CheckCircle size={14} className="text-emerald-400" />
                <p className="text-emerald-300 text-sm">
                  Face matched <span className="font-mono text-emerald-400">({Math.round(similarity * 100)}%)</span>
                </p>
              </div>
            )}

            <div className="text-center">
              <Fingerprint size={40} className="text-blue-400 mx-auto mb-2" />
              <p className="text-slate-200 font-semibold">Enter PIN</p>
              <p className="text-slate-500 text-xs mt-1">4-digit security PIN</p>
            </div>

            {/* PIN dots */}
            <div className="flex gap-3">
              {[0, 1, 2, 3].map(i => (
                <div key={i}
                     className={`w-13 h-13 w-12 h-12 rounded-xl border-2 flex items-center justify-center text-2xl transition-all duration-150
                       ${pin.length > i
                         ? "border-emerald-400 bg-emerald-400/15 text-emerald-300"
                         : "border-slate-700 text-slate-700"}`}>
                  {pin.length > i ? "●" : "○"}
                </div>
              ))}
            </div>

            {/* Numpad */}
            <div className="grid grid-cols-3 gap-2 w-52">
              {[1,2,3,4,5,6,7,8,9,"",0,"⌫"].map((d, i) => (
                <button key={i} disabled={isLoading}
                        onClick={() => {
                          if (d === "⌫") setPin(p => p.slice(0, -1));
                          else if (d !== "") handlePinDigit(String(d));
                        }}
                        className={`h-12 rounded-xl text-lg font-semibold transition-all
                          ${d === "" ? "invisible" : "bg-slate-800 hover:bg-slate-700 text-white active:scale-95 disabled:opacity-50"}`}>
                  {d}
                </button>
              ))}
            </div>

            {isLoading && (
              <div className="flex items-center gap-2 text-blue-400 text-sm">
                <div className="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                Verifying PIN...
              </div>
            )}

            {error && <ErrorBanner message={error} />}

            <button onClick={reset} className="text-slate-500 text-xs hover:text-slate-300 transition-colors flex items-center gap-1">
              <RefreshCw size={11} /> Re-scan face
            </button>
          </div>
        )}

        {/* ── STEP: EMERGENCY BYPASS ─────────────────────────────────────── */}
        {step === STEPS.BYPASS && (
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2 p-3 bg-amber-500/10 border border-amber-500/30 rounded-xl">
              <Zap size={15} className="text-amber-400 flex-shrink-0" />
              <p className="text-amber-300 text-xs font-medium">
                Emergency Override — SuperDoctor access. All lookups are audited.
              </p>
            </div>

            {/* Bypass type selector */}
            <div className="flex gap-2">
              {[
                { id: "patient_id", label: "Patient ID",     icon: <Hash size={12}/> },
                { id: "phone",      label: "Phone Number",   icon: <Phone size={12}/> },
              ].map(t => (
                <button key={t.id} onClick={() => setBypassType(t.id)}
                        className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl text-xs font-medium transition-all border
                          ${bypassType === t.id
                            ? "bg-blue-500/20 border-blue-500/40 text-blue-400"
                            : "border-slate-700 text-slate-500 hover:border-slate-600 hover:text-slate-300"}`}>
                  {t.icon} {t.label}
                </button>
              ))}
            </div>

            <input
              value={bypassQuery}
              onChange={e => { setBypassQuery(e.target.value); setError(null); }}
              onKeyDown={e => e.key === "Enter" && handleBypass()}
              placeholder={bypassType === "patient_id" ? "e.g. P-0042" : "e.g. +1 (555) 204-8891"}
              className="w-full bg-slate-800 border border-slate-700 focus:border-emerald-500/60 rounded-xl px-4 py-3 text-white placeholder-slate-500 text-sm outline-none transition-colors"
            />

            {error && <ErrorBanner message={error} />}

            <button onClick={handleBypass} disabled={isLoading}
                    className="w-full py-3 bg-amber-500 hover:bg-amber-400 disabled:opacity-60 text-black font-bold rounded-xl transition-all text-sm flex items-center justify-center gap-2">
              {isLoading
                ? <><div className="w-4 h-4 border-2 border-black border-t-transparent rounded-full animate-spin" /> Searching...</>
                : <><Zap size={15}/> Emergency Lookup</>}
            </button>
          </div>
        )}

        {/* ── STEP: SUCCESS ───────────────────────────────────────────────── */}
        {step === STEPS.SUCCESS && (
          <div className="flex flex-col items-center gap-4 py-4">
            <div className="w-16 h-16 rounded-full bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center">
              <CheckCircle size={32} className="text-emerald-400" />
            </div>
            <p className="text-white font-bold text-lg">Access Granted</p>
            <p className="text-slate-400 text-sm">Redirecting…</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Error Banner ─────────────────────────────────────────────────────────────
function ErrorBanner({ message, onRetry }) {
  return (
    <div className="flex items-start gap-2 w-full px-3 py-2.5 bg-red-500/10 border border-red-500/30 rounded-xl">
      <AlertCircle size={14} className="text-red-400 mt-0.5 flex-shrink-0" />
      <div className="flex-1">
        <p className="text-red-300 text-xs">{message}</p>
        {onRetry && (
          <button onClick={onRetry} className="text-red-400 text-xs underline mt-1">Try again</button>
        )}
      </div>
    </div>
  );
}
