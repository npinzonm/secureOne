"use client";

import type { ReactNode } from "react";
import { AdminLayout } from "@/components/Shell";

export default function Layout({ children }: { children: ReactNode }) {
  return <AdminLayout>{children}</AdminLayout>;
}
