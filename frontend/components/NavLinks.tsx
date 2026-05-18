"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/events", label: "Events" },
  { href: "/resources", label: "Resources" },
  { href: "/system", label: "System" },
  { href: "/settings", label: "Settings" },
] as const;

const NAV_SECONDARY = [
  { href: "/feedback", label: "Feedback" },
] as const;

export default function NavLinks() {
  const pathname = usePathname();
  return (
    <>
      {NAV_LINKS.map(({ href, label }) => {
        const isActive = pathname === href || pathname.startsWith(href + "/");
        return (
          <Link key={href} href={href} className={isActive ? "active" : undefined}>
            {label}
          </Link>
        );
      })}
      {NAV_SECONDARY.map(({ href, label }) => {
        const isActive = pathname === href || pathname.startsWith(href + "/");
        return (
          <Link key={href} href={href} className={`nav-secondary${isActive ? " active" : ""}`}>
            {label}
          </Link>
        );
      })}
    </>
  );
}
