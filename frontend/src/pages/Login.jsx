import React, { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatApiError } from "@/lib/api";
import { toast } from "sonner";

const BG = "https://images.unsplash.com/photo-1547895749-888a559fc2a7?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjY2NzN8MHwxfHNlYXJjaHwxfHxtb2Rlcm4lMjBpbmR1c3RyaWFsJTIwcGxhbnQlMjBjbGVhbiUyMGFyY2hpdGVjdHVyZXxlbnwwfHx8fDE3ODcyMDIyNjh8MA&ixlib=rb-4.1.0&q=85";

export default function Login({ mode = "login" }) {
  const nav = useNavigate();
  const { login, register } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const isRegister = mode === "register";
  const submitLabel = isRegister ? "Create Account" : "Sign In";
  const eyebrow = isRegister ? "Create Account" : "Sign In";
  const heading = isRegister ? "Join the tracker." : "Welcome back.";

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      if (isRegister) await register(email, password, name);
      else await login(email, password);
      toast.success("Signed in");
      nav("/");
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      <div className="hidden lg:block relative" style={{ backgroundImage: `url(${BG})`, backgroundSize: "cover", backgroundPosition: "center" }}>
        <div className="absolute inset-0 bg-neutral-900/75" />
        <div className="relative z-10 h-full flex flex-col justify-between p-10 text-white">
          <div className="bg-white px-4 py-3 inline-flex w-fit border border-neutral-200">
            <img src="/rudaya-logo.png" alt="Rudaya Powers Pvt. Ltd." className="h-10 w-auto object-contain" data-testid="login-logo" />
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.3em] text-yellow-400 mb-3">Finance Tracker</div>
            <h1 className="font-heading text-5xl font-bold leading-tight tracking-tight">
              Precision<br />in every entry.
            </h1>
            <p className="mt-4 text-neutral-300 max-w-md">
              Revenue, cost & expense — tracked project-by-project. A single source of truth for Rudaya Powers Pvt. Ltd.
            </p>
          </div>
          <div className="text-xs text-neutral-400 font-mono-tab">© {new Date().getFullYear()} · Rudaya Powers Pvt. Ltd.</div>
        </div>
      </div>
      <div className="flex items-center justify-center p-6 lg:p-16 bg-white">
        <div className="w-full max-w-md">
          <div className="lg:hidden mb-8">
            <img src="/rudaya-logo.png" alt="Rudaya Powers Pvt. Ltd." className="h-10 w-auto object-contain" />
          </div>
          <div className="text-xs uppercase tracking-[0.3em] text-neutral-500 mb-2">{eyebrow}</div>
          <h2 className="font-heading text-3xl font-bold tracking-tight mb-8">{heading}</h2>
          <form onSubmit={submit} className="space-y-5">
            {isRegister && (
              <div>
                <Label htmlFor="name" className="text-xs uppercase tracking-wider">Name</Label>
                <Input id="name" data-testid="register-name-input" value={name} onChange={(e) => setName(e.target.value)} className="mt-1 rounded-none border-neutral-300 focus-visible:ring-neutral-900 focus-visible:ring-2" />
              </div>
            )}
            <div>
              <Label htmlFor="email" className="text-xs uppercase tracking-wider">Email</Label>
              <Input id="email" data-testid="login-email-input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1 rounded-none border-neutral-300 focus-visible:ring-neutral-900 focus-visible:ring-2" />
            </div>
            <div>
              <Label htmlFor="password" className="text-xs uppercase tracking-wider">Password</Label>
              <Input id="password" data-testid="login-password-input" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 rounded-none border-neutral-300 focus-visible:ring-neutral-900 focus-visible:ring-2" />
            </div>
            <Button data-testid="login-submit-button" type="submit" disabled={loading} className="w-full rounded-none bg-neutral-900 hover:bg-neutral-700 h-11 font-semibold tracking-wide">
              {loading ? "Please wait…" : submitLabel}
            </Button>
          </form>
          <div className="mt-6 text-sm text-neutral-600">
            {isRegister ? (
              <>Already have an account? <Link data-testid="link-to-login" to="/login" className="text-neutral-900 font-medium underline underline-offset-4">Sign in</Link></>
            ) : (
              <>New teammate? <Link data-testid="link-to-register" to="/register" className="text-neutral-900 font-medium underline underline-offset-4">Create an account</Link></>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
