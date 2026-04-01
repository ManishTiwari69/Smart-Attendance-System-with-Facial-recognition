/**
 * frontend/src/hooks/useAuth.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Auth hook that implements the full biometric 2FA flow:
 *
 *   1. faceVerify(userId, base64Image)    → {success, faceToken, similarity}
 *   2. pinVerify(faceToken, pin)          → {success, accessToken, user}
 *   3. emergencyLookup(queryType, query)  → {success, patient}  (SuperDoctor only)
 *   4. enrollFace(userId, images[])       → {enrolled, warnings}
 *   5. logout()
 *
 * Also exposes:
 *   user          – decoded JWT payload   { id, name, role }
 *   isLoading
 *   error
 *   isSuperDoctor – boolean shorthand
 */

import { useState, useCallback, createContext, useContext, useEffect } from "react";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:5000/api";

// ─── Auth Context ─────────────────────────────────────────────────────────────
const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const auth = _useAuthState();
  return <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

// ─── Core Hook ────────────────────────────────────────────────────────────────
function _useAuthState() {
  const [user,       setUser]       = useState(null);
  const [isLoading,  setIsLoading]  = useState(false);
  const [error,      setError]      = useState(null);

  // Restore session from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem("sh_access_token");
    if (stored) {
      try {
        const payload = _decodeJWT(stored);
        if (payload.exp * 1000 > Date.now()) {
          setUser({ id: payload.sub, name: payload.name, role: payload.role });
        } else {
          localStorage.removeItem("sh_access_token");
        }
      } catch {
        localStorage.removeItem("sh_access_token");
      }
    }
  }, []);

  // ── Step 1: Face Verification ─────────────────────────────────────────────
  const faceVerify = useCallback(async (userId, base64Image) => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await _post("/auth/face/verify", {
        user_id: userId,
        image:   base64Image,
      });
      return res;   // { success, face_token, similarity, message }
    } catch (err) {
      setError(err.message);
      return { success: false, message: err.message };
    } finally {
      setIsLoading(false);
    }
  }, []);

  // ── Step 2: PIN Verification → full tokens ────────────────────────────────
  const pinVerify = useCallback(async (faceToken, pin) => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await _post("/auth/pin/verify", {
        face_token: faceToken,
        pin,
      });
      if (res.success && res.access_token) {
        localStorage.setItem("sh_access_token",  res.access_token);
        localStorage.setItem("sh_refresh_token", res.refresh_token || "");
        const payload = _decodeJWT(res.access_token);
        setUser({ id: payload.sub, name: payload.name, role: payload.role });
      }
      return res;
    } catch (err) {
      setError(err.message);
      return { success: false, message: err.message };
    } finally {
      setIsLoading(false);
    }
  }, []);

  // ── SuperDoctor Emergency Bypass ──────────────────────────────────────────
  const emergencyLookup = useCallback(async (queryType, query, image = null) => {
    setIsLoading(true);
    setError(null);
    try {
      return await _post("/auth/emergency/lookup", {
        query_type: queryType,
        query,
        image,
      }, _getToken());
    } catch (err) {
      setError(err.message);
      return { success: false, message: err.message };
    } finally {
      setIsLoading(false);
    }
  }, []);

  // ── Face Enrolment ────────────────────────────────────────────────────────
  const enrollFace = useCallback(async (userId, images) => {
    setIsLoading(true);
    setError(null);
    try {
      return await _post("/auth/face/enroll", { user_id: userId, images }, _getToken());
    } catch (err) {
      setError(err.message);
      return { success: false, enrolled: 0, warnings: [err.message] };
    } finally {
      setIsLoading(false);
    }
  }, []);

  // ── Logout ────────────────────────────────────────────────────────────────
  const logout = useCallback(async () => {
    const refreshToken = localStorage.getItem("sh_refresh_token");
    try {
      await _post("/auth/logout", { refresh_token: refreshToken }, _getToken());
    } catch { /* ignore */ }
    localStorage.removeItem("sh_access_token");
    localStorage.removeItem("sh_refresh_token");
    setUser(null);
  }, []);

  return {
    user,
    isLoading,
    error,
    isSuperDoctor: user?.role === "superDoctor",
    isAdmin:       user?.role === "admin",
    isDoctor:      user?.role === "doctor" || user?.role === "superDoctor",
    isStaff:       user?.role === "staff",
    isPatient:     user?.role === "patient",
    faceVerify,
    pinVerify,
    emergencyLookup,
    enrollFace,
    logout,
    getToken: _getToken,
  };
}

// ─── HTTP Helpers ─────────────────────────────────────────────────────────────

async function _post(path, body, token = null) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE_URL}${path}`, {
    method:      "POST",
    headers,
    credentials: "include",
    body:        JSON.stringify(body),
  });

  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || data.message || `HTTP ${res.status}`);
  }
  return data;
}

async function _get(path, token = null) {
  const headers = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res  = await fetch(`${BASE_URL}${path}`, { headers, credentials: "include" });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function _getToken() {
  return localStorage.getItem("sh_access_token");
}

function _decodeJWT(token) {
  const [, payload] = token.split(".");
  return JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
}

// ─── API Client (for non-auth calls) ─────────────────────────────────────────
export const api = {
  get:  (path)       => _get(path, _getToken()),
  post: (path, body) => _post(path, body, _getToken()),
};
