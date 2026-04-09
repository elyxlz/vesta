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
  onDelete: () => void;
}

export interface MenuProps {
  state: MenuState;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trigger: React.ReactNode;
}
