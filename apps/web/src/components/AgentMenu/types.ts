export interface MenuState {
  name: string;
  isRunning: boolean;
  showAliveActions: boolean | undefined;
  isBusy: boolean;
  onToggle: () => void;
  onLogs: () => void;
  onAppSettings: () => void;
  onAgentSettings: () => void;
  onRestart: () => void;
  onBackup: () => void;
  onAuthenticate?: () => void;
  isAuthenticated?: boolean;
  onDelete: () => void;
  onDebugInfo?: () => void;
}

export interface MenuProps {
  state: MenuState;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trigger: React.ReactNode;
}
