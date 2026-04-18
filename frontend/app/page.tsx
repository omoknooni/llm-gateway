import DashboardClient from "./dashboard-client";

export const dynamic = "force-dynamic";

function resolveUrl(value: string | undefined, fallback: string): string {
  const trimmed = value?.trim();
  if (!trimmed) {
    return fallback;
  }
  return trimmed;
}

export default function Page() {
  const backendUrl = resolveUrl(process.env.NEXT_PUBLIC_BACKEND_URL, "http://localhost:8000");
  const gatewayUrl = resolveUrl(process.env.NEXT_PUBLIC_GATEWAY_URL, "http://localhost:4000");
  const litellmUiUrl = resolveUrl(process.env.NEXT_PUBLIC_LITELLM_UI_URL, "http://localhost:4000/ui");

  return (
    <DashboardClient
      backendUrl={backendUrl}
      gatewayUrl={gatewayUrl}
      litellmUiUrl={litellmUiUrl}
    />
  );
}
