export interface MenuState {
  name: string;
  isRunning: boolean;
  showAliveActions: boolean | undefined;
  isBusy: boolean;
  showToolCalls: boolean;
  onToggle: () => void;
  onLogs: () => void;
  onToolCalls: () => void;
  onOpenSettings: () => void;
  onRestart: () => void;
  onRebuild: () => void;
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
