export interface MenuState {
  name: string;
  isRunning: boolean;
  showAliveActions: boolean | undefined;
  isBusy: boolean;
  onToggle: () => void;
  onLogs: () => void;
  onServices: () => void;
  onAppSettings: () => void;
  onAgentSettings: () => void;
  onSwitchGateway: () => void;
  onRestart: () => void;
  onBackup: () => void;
  onAuthenticate?: () => void;
  isAuthenticated?: boolean;
  onDelete: () => void;
}

export interface MenuProps {
  state: MenuState;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trigger: React.ReactNode;
}
