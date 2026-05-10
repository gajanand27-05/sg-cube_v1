-- ============================================================================
-- SG_CUBE Phase 2 — Initial Migration
-- Run this once in Supabase Dashboard → SQL Editor.
-- Idempotent (safe to re-run).
-- ============================================================================

-- ── Tables ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.profiles (
    id                UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email             TEXT NOT NULL,
    role              TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
    is_approved_admin BOOLEAN NOT NULL DEFAULT FALSE,
    mode              TEXT NOT NULL DEFAULT 'personal' CHECK (mode IN ('personal','assistive')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.admin_requests (
    id           BIGSERIAL PRIMARY KEY,
    user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_admin_requests_status ON public.admin_requests(status);
CREATE INDEX IF NOT EXISTS idx_admin_requests_user_id ON public.admin_requests(user_id);

CREATE TABLE IF NOT EXISTS public.command_logs (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    input_text      TEXT NOT NULL,
    resolved_action JSONB,
    source_layer    TEXT CHECK (source_layer IN ('cache','rule','llm')),
    status          TEXT CHECK (status IN ('success','blocked','error')),
    latency_ms      INTEGER,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_command_logs_user_ts ON public.command_logs(user_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS public.context_memory (
    id         BIGSERIAL PRIMARY KEY,
    user_id    UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    session_id TEXT,
    key        TEXT,
    value      TEXT,
    timestamp  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_context_memory_user_session ON public.context_memory(user_id, session_id);

-- ── Trigger: auto-create profile on signup ─────────────────────────────────

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.profiles (id, email)
    VALUES (NEW.id, NEW.email)
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ── Row Level Security ─────────────────────────────────────────────────────
-- Service-role key bypasses RLS automatically — used by the backend.
-- Anon-key clients (when we add a frontend) hit these policies.

ALTER TABLE public.profiles        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_requests  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.command_logs    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.context_memory  ENABLE ROW LEVEL SECURITY;

-- profiles
DROP POLICY IF EXISTS "users read own profile" ON public.profiles;
CREATE POLICY "users read own profile" ON public.profiles
    FOR SELECT USING (auth.uid() = id);

DROP POLICY IF EXISTS "users update own profile" ON public.profiles;
CREATE POLICY "users update own profile" ON public.profiles
    FOR UPDATE USING (auth.uid() = id);

-- admin_requests
DROP POLICY IF EXISTS "users read own admin_requests" ON public.admin_requests;
CREATE POLICY "users read own admin_requests" ON public.admin_requests
    FOR SELECT USING (auth.uid() = user_id);

-- command_logs
DROP POLICY IF EXISTS "users read own command_logs" ON public.command_logs;
CREATE POLICY "users read own command_logs" ON public.command_logs
    FOR SELECT USING (auth.uid() = user_id);

-- context_memory
DROP POLICY IF EXISTS "users read own context_memory" ON public.context_memory;
CREATE POLICY "users read own context_memory" ON public.context_memory
    FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "users write own context_memory" ON public.context_memory;
CREATE POLICY "users write own context_memory" ON public.context_memory
    FOR ALL USING (auth.uid() = user_id);
