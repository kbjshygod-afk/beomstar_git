import { cookies } from "next/headers";
import { AUTH_COOKIE_NAME, isAuthCookieValid } from "../lib/auth";
import LoginForm from "./login-form";
import CostTable from "./cost-table";

export default async function Home() {
  const cookieStore = await cookies();
  const authCookie = cookieStore.get(AUTH_COOKIE_NAME)?.value;
  const authenticated = isAuthCookieValid(authCookie);

  return (
    <main className="page">
      {authenticated ? <CostTable /> : <LoginForm />}
    </main>
  );
}
