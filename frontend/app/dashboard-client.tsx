"use client";

import { FormEvent, useEffect, useState } from "react";

type Team = {
  id: number;
  name: string;
  description?: string | null;
  created_at: string;
};

type User = {
  id: number;
  email: string;
  name: string;
  team_id?: number | null;
  is_active: boolean;
  created_at: string;
};

type Model = {
  id: number;
  alias: string;
  provider: string;
  provider_model_id: string;
  input_cost_per_1k: number;
  output_cost_per_1k: number;
  active: boolean;
  created_at: string;
};

type VirtualKey = {
  id: number;
  key_prefix: string;
  masked_key: string;
  owner_type: string;
  team_id?: number | null;
  user_id?: number | null;
  allowed_model_aliases: string[];
  status: string;
  created_at: string;
};

type UsageSummary = {
  total_requests: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  total_estimated_cost_usd: number;
  success_count: number;
  failure_count: number;
};

type LeaderboardEntry = {
  label: string;
  request_count: number;
  total_tokens: number;
  estimated_cost_usd: number;
};

type Leaderboards = {
  teams: LeaderboardEntry[];
  users: LeaderboardEntry[];
  models: LeaderboardEntry[];
};

type DashboardClientProps = {
  backendUrl: string;
  gatewayUrl: string;
  litellmUiUrl: string;
};

function joinUrl(baseUrl: string, path: string): string {
  if (!baseUrl) {
    return path;
  }
  const normalizedBase = baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
  return `${normalizedBase}${path}`;
}

async function apiFetch<T>(backendUrl: string, path: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(joinUrl(backendUrl, path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed for ${path}`);
  }
  return response.json();
}

export default function DashboardClient({
  backendUrl,
  gatewayUrl,
  litellmUiUrl,
}: DashboardClientProps) {
  const [token, setToken] = useState<string>("");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123!");
  const [teams, setTeams] = useState<Team[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [keys, setKeys] = useState<VirtualKey[]>([]);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [leaderboards, setLeaderboards] = useState<Leaderboards | null>(null);
  const [notice, setNotice] = useState<string>("");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    const existing = window.localStorage.getItem("admin-token");
    if (existing) {
      setToken(existing);
    }
  }, []);

  useEffect(() => {
    if (!token) {
      return;
    }
    window.localStorage.setItem("admin-token", token);
    void loadDashboard(token);
  }, [token]);

  async function loadDashboard(authToken: string) {
    try {
      const [teamData, userData, modelData, keyData, usageData, leaderboardData] = await Promise.all([
        apiFetch<Team[]>(backendUrl, "/admin/teams", authToken),
        apiFetch<User[]>(backendUrl, "/admin/users", authToken),
        apiFetch<Model[]>(backendUrl, "/admin/models", authToken),
        apiFetch<VirtualKey[]>(backendUrl, "/admin/keys", authToken),
        apiFetch<UsageSummary>(backendUrl, "/admin/usage", authToken),
        apiFetch<Leaderboards>(backendUrl, "/admin/leaderboards", authToken),
      ]);
      setTeams(teamData);
      setUsers(userData);
      setModels(modelData);
      setKeys(keyData);
      setUsage(usageData);
      setLeaderboards(leaderboardData);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard");
    }
  }

  async function login(event: FormEvent) {
    event.preventDefault();
    setError("");
    const response = await fetch(joinUrl(backendUrl, "/admin/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!response.ok) {
      setError("Login failed");
      return;
    }
    const data = (await response.json()) as { access_token: string };
    setToken(data.access_token);
  }

  async function handleCreateTeam(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = {
      name: String(form.get("name") || ""),
      description: String(form.get("description") || ""),
    };
    await apiFetch(backendUrl, "/admin/teams", token, { method: "POST", body: JSON.stringify(payload) });
    setNotice(`Created team ${payload.name}`);
    event.currentTarget.reset();
    await loadDashboard(token);
  }

  async function handleCreateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = {
      email: String(form.get("email") || ""),
      name: String(form.get("name") || ""),
      team_id: Number(form.get("team_id") || 0) || null,
    };
    await apiFetch(backendUrl, "/admin/users", token, { method: "POST", body: JSON.stringify(payload) });
    setNotice(`Created user ${payload.name}`);
    event.currentTarget.reset();
    await loadDashboard(token);
  }

  async function handleCreateModel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = {
      alias: String(form.get("alias") || ""),
      provider: "bedrock",
      provider_model_id: String(form.get("provider_model_id") || ""),
      input_cost_per_1k: Number(form.get("input_cost_per_1k") || 0),
      output_cost_per_1k: Number(form.get("output_cost_per_1k") || 0),
      active: true,
    };
    await apiFetch(backendUrl, "/admin/models", token, { method: "POST", body: JSON.stringify(payload) });
    setNotice(`Created model alias ${payload.alias}`);
    event.currentTarget.reset();
    await loadDashboard(token);
  }

  async function handleCreateKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const allowed = String(form.get("allowed_model_aliases") || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    const payload = {
      owner_type: String(form.get("owner_type") || "team"),
      team_id: Number(form.get("team_id") || 0) || null,
      user_id: Number(form.get("user_id") || 0) || null,
      allowed_model_aliases: allowed,
      expires_at: null,
    };
    const response = await apiFetch<{ key: string; record: VirtualKey }>(backendUrl, "/admin/keys", token, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setNotice(`Issued key once: ${response.key}`);
    event.currentTarget.reset();
    await loadDashboard(token);
  }

  async function rotateKey(id: number) {
    const response = await apiFetch<{ key: string }>(backendUrl, `/admin/keys/${id}/rotate`, token, {
      method: "POST",
    });
    setNotice(`Rotated key. New secret: ${response.key}`);
    await loadDashboard(token);
  }

  async function revokeKey(id: number) {
    await apiFetch(backendUrl, `/admin/keys/${id}/revoke`, token, { method: "POST" });
    setNotice(`Revoked key #${id}`);
    await loadDashboard(token);
  }

  async function syncLiteLLM() {
    const response = await apiFetch<{ detail: string }>(backendUrl, "/internal/litellm/sync", token, {
      method: "POST",
    });
    setNotice(response.detail);
  }

  if (!token) {
    return (
      <main className="page">
        <section className="panel login-card">
          <h1>LLM Gateway Admin</h1>
          <p className="muted">로컬 더미 관리자 로그인으로 control plane과 커스텀 UI를 바로 확인할 수 있습니다.</p>
          <form className="form-grid" onSubmit={login}>
            <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="username" />
            <input value={password} onChange={(e) => setPassword(e.target.value)} placeholder="password" type="password" />
            <button type="submit">로그인</button>
          </form>
          {error ? <div className="banner">{error}</div> : null}
        </section>
      </main>
    );
  }

  return (
    <main className="page">
      <section className="hero">
        <div className="hero-grid">
          <div>
            <h1>LiteLLM Gateway Control Plane</h1>
            <p>
              Virtual Key, 모델 alias, 팀/사용자 정책을 backend가 관리하고, LiteLLM은 실제 OpenAI 호환 Gateway로
              동작하는 구조입니다. 커스텀 관리자 UI를 기본으로 사용하고, LiteLLM UI는 fallback 운영 도구로 연결합니다.
            </p>
            <div className="quick-links">
              <a className="chip" href={joinUrl(backendUrl, "/docs")} target="_blank">FastAPI Docs</a>
              <a className="chip" href={gatewayUrl} target="_blank">Gateway Base URL</a>
              <a className="chip" href={litellmUiUrl} target="_blank">LiteLLM UI Fallback</a>
            </div>
          </div>
          <div>
            <div className="toolbar">
              <button onClick={() => loadDashboard(token)}>새로고침</button>
              <button className="subtle" onClick={syncLiteLLM}>LiteLLM 동기화</button>
            </div>
            {notice ? <div className="banner">{notice}</div> : null}
            {error ? <div className="banner">{error}</div> : null}
          </div>
        </div>
      </section>

      <section className="content">
        <div className="panel">
          <h2>Overview</h2>
          <div className="stats">
            <div className="stat">
              <span className="muted">Requests</span>
              <strong>{usage?.total_requests ?? 0}</strong>
            </div>
            <div className="stat">
              <span className="muted">Total Tokens</span>
              <strong>{usage?.total_tokens ?? 0}</strong>
            </div>
            <div className="stat">
              <span className="muted">Estimated Cost</span>
              <strong>${(usage?.total_estimated_cost_usd ?? 0).toFixed(4)}</strong>
            </div>
            <div className="stat">
              <span className="muted">Success / Failure</span>
              <strong>{usage?.success_count ?? 0} / {usage?.failure_count ?? 0}</strong>
            </div>
          </div>
        </div>

        <div className="panel half">
          <h2>Teams</h2>
          <form className="form-grid" onSubmit={handleCreateTeam}>
            <input name="name" placeholder="platform" />
            <input name="description" placeholder="description" />
            <button type="submit">팀 생성</button>
          </form>
          <table className="table">
            <thead>
              <tr><th>Name</th><th>Description</th></tr>
            </thead>
            <tbody>
              {teams.map((team) => (
                <tr key={team.id}>
                  <td>{team.name}</td>
                  <td>{team.description || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel half">
          <h2>Users</h2>
          <form className="form-grid" onSubmit={handleCreateUser}>
            <input name="name" placeholder="Alice" />
            <input name="email" placeholder="alice@example.internal" />
            <select name="team_id" defaultValue="">
              <option value="">team(optional)</option>
              {teams.map((team) => (
                <option key={team.id} value={team.id}>{team.name}</option>
              ))}
            </select>
            <button type="submit">사용자 생성</button>
          </form>
          <table className="table">
            <thead>
              <tr><th>Name</th><th>Email</th><th>Team</th></tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td>{user.name}</td>
                  <td>{user.email}</td>
                  <td>{teams.find((team) => team.id === user.team_id)?.name || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel half">
          <h2>Model Aliases</h2>
          <form className="form-grid" onSubmit={handleCreateModel}>
            <input name="alias" placeholder="claude-sonnet" />
            <input name="provider_model_id" placeholder="anthropic.claude-..." />
            <input name="input_cost_per_1k" placeholder="0" type="number" step="0.000001" />
            <input name="output_cost_per_1k" placeholder="0" type="number" step="0.000001" />
            <button type="submit">모델 등록</button>
          </form>
          <table className="table">
            <thead>
              <tr><th>Alias</th><th>Provider Model</th><th>Status</th></tr>
            </thead>
            <tbody>
              {models.map((model) => (
                <tr key={model.id}>
                  <td>{model.alias}</td>
                  <td>{model.provider_model_id}</td>
                  <td><span className={`pill ${model.active ? "" : "warn"}`}>{model.active ? "active" : "inactive"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel half">
          <h2>Virtual Keys</h2>
          <form className="form-grid" onSubmit={handleCreateKey}>
            <select name="owner_type" defaultValue="team">
              <option value="team">team</option>
              <option value="user">user</option>
            </select>
            <select name="team_id" defaultValue="">
              <option value="">team(optional)</option>
              {teams.map((team) => (
                <option key={team.id} value={team.id}>{team.name}</option>
              ))}
            </select>
            <select name="user_id" defaultValue="">
              <option value="">user(optional)</option>
              {users.map((user) => (
                <option key={user.id} value={user.id}>{user.name}</option>
              ))}
            </select>
            <input name="allowed_model_aliases" placeholder="claude-sonnet,claude-haiku" />
            <button type="submit">키 발급</button>
          </form>
          <table className="table">
            <thead>
              <tr><th>Key</th><th>Owner</th><th>Allowed Models</th><th>Status</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {keys.map((key) => (
                <tr key={key.id}>
                  <td>{key.masked_key}</td>
                  <td>{key.owner_type}:{key.team_id ?? key.user_id ?? "-"}</td>
                  <td>{key.allowed_model_aliases.join(", ") || "-"}</td>
                  <td><span className={`pill ${key.status === "active" ? "" : "warn"}`}>{key.status}</span></td>
                  <td>
                    <div className="toolbar">
                      <button type="button" className="subtle" onClick={() => rotateKey(key.id)}>rotate</button>
                      <button type="button" onClick={() => revokeKey(key.id)}>revoke</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <h2>Leaderboards</h2>
          <div className="grid-2">
            <LeaderboardTable title="Teams" items={leaderboards?.teams ?? []} />
            <LeaderboardTable title="Users" items={leaderboards?.users ?? []} />
          </div>
          <div style={{ marginTop: 18 }}>
            <LeaderboardTable title="Models" items={leaderboards?.models ?? []} />
          </div>
        </div>
      </section>
    </main>
  );
}

function LeaderboardTable({ title, items }: { title: string; items: LeaderboardEntry[] }) {
  return (
    <div>
      <h3>{title}</h3>
      <table className="table">
        <thead>
          <tr>
            <th>Label</th>
            <th>Requests</th>
            <th>Tokens</th>
            <th>Cost</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={`${title}-${item.label}`}>
              <td>{item.label}</td>
              <td>{item.request_count}</td>
              <td>{item.total_tokens}</td>
              <td>${item.estimated_cost_usd.toFixed(4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
