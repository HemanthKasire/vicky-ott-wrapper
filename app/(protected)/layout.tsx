import { requirePortalSession } from "@/lib/portal-auth";

export const dynamic = "force-dynamic";

export default async function ProtectedLayout({ children }: { children: React.ReactNode }) {
  await requirePortalSession();
  return children;
}
