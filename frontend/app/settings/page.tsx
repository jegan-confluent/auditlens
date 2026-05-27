"use client";

import { useEffect, useState } from "react";
import { ActorMappingsTab } from "./components/ActorMappingsTab";
import { ColdStorageTab } from "./components/ColdStorageTab";
import { NotificationsTab } from "./components/NotificationsTab";
import { ResourceCatalogTab } from "./components/ResourceCatalogTab";
import { RetentionTab } from "./components/RetentionTab";
import { SchemaRegistryTab } from "./components/SchemaRegistryTab";
import { StreamOutputTab } from "./components/StreamOutputTab";
import { API_BASE } from "./components/shared";
import { TableflowTab } from "./components/TableflowTab";

const TABS = ["Retention", "Cold Storage", "Notifications", "Actor Mappings", "Resource Catalog", "Schema Registry", "Stream Output", "Tableflow"] as const;
type Tab = (typeof TABS)[number];

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("Retention");
  const [accessDenied, setAccessDenied] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/settings/retention`, { cache: "no-store" })
      .then((r) => { if (r.status === 401 || r.status === 403) setAccessDenied(true); })
      .catch(() => {});
  }, []);

  if (accessDenied) {
    return (
      <main className="page">
        <h1>Settings</h1>
        <div className="settings-access-denied">Access denied — admin token required.</div>
      </main>
    );
  }

  return (
    <main className="page">
      <h1>Settings</h1>
      <div className="settings-tabs">
        {TABS.map((tab) => (
          <button
            key={tab}
            className={`settings-tab-btn${activeTab === tab ? " active" : ""}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>
      <div className="settings-tab-content">
        {activeTab === "Retention" && <RetentionTab />}
        {activeTab === "Cold Storage" && <ColdStorageTab />}
        {activeTab === "Notifications" && <NotificationsTab />}
        {activeTab === "Actor Mappings" && <ActorMappingsTab />}
        {activeTab === "Resource Catalog" && <ResourceCatalogTab />}
        {activeTab === "Schema Registry" && <SchemaRegistryTab />}
        {activeTab === "Stream Output" && (
          <StreamOutputTab
            onGotoSchemaRegistry={() => setActiveTab("Schema Registry")}
            onGotoTableflow={() => setActiveTab("Tableflow")}
          />
        )}
        {activeTab === "Tableflow" && <TableflowTab />}
      </div>
    </main>
  );
}
