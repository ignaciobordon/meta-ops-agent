/**
 * Global state management with Zustand
 */
import { create } from 'zustand';
import { MetaActiveAccount, MetaAdAccount, Organization } from '../services/api';

interface AppUser {
  id: string;
  name: string;
  email: string;
  role: string;
}

interface AppState {
  // Current workspace
  currentOrg: Organization | null;
  setCurrentOrg: (org: Organization | null) => void;

  // Current user (populated by auth flow)
  currentUser: AppUser | null;
  setCurrentUser: (user: AppUser | null) => void;

  // Meta connection state (FASE 5.4)
  activeAdAccount: MetaActiveAccount | null;
  setActiveAdAccount: (account: MetaActiveAccount | null) => void;
  adAccounts: MetaAdAccount[];
  setAdAccounts: (accounts: MetaAdAccount[]) => void;
  metaConnected: boolean;
  setMetaConnected: (connected: boolean) => void;

  // UI state
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
}

export const useStore = create<AppState>((set) => ({
  // Workspace
  currentOrg: null,
  setCurrentOrg: (org) => set({ currentOrg: org }),

  // User — starts null, populated by auth flow
  currentUser: null,
  setCurrentUser: (user) => set({ currentUser: user }),

  // Meta (FASE 5.4)
  activeAdAccount: null,
  setActiveAdAccount: (account) =>
    set({ activeAdAccount: account, metaConnected: account?.has_active_account ?? false }),
  adAccounts: [],
  setAdAccounts: (accounts) => set({ adAccounts: accounts }),
  metaConnected: false,
  setMetaConnected: (connected) => set({ metaConnected: connected }),

  // UI
  sidebarCollapsed: false,
  toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
}));
