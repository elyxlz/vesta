import type { DeviceInfo, DevicePosition, Tree } from "../protocol/tree";

export function selectDevices(tree: Tree | null): DeviceInfo[] {
  return tree?.devices ?? [];
}

// Structural compare so an unrelated tree delta (an agent update, a notification) does not hand every
// devices consumer a fresh array through useReplica.
export function devicesEqual(a: DeviceInfo[], b: DeviceInfo[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((device, index) => {
    const other = b[index];
    if (other === undefined) return false;
    return (
      other.id === device.id &&
      other.kind === device.kind &&
      other.descriptor === device.descriptor &&
      other.present === device.present &&
      other.lastSeen === device.lastSeen &&
      other.pushEnabled === device.pushEnabled &&
      other.timezone === device.timezone &&
      other.positionAt === device.positionAt &&
      positionEqual(other.position, device.position)
    );
  });
}

function positionEqual(
  a: DevicePosition | null,
  b: DevicePosition | null,
): boolean {
  if (a === null || b === null) return a === b;
  return (
    a.latitude === b.latitude &&
    a.longitude === b.longitude &&
    a.accuracyM === b.accuracyM &&
    a.place?.city === b.place?.city &&
    a.place?.region === b.place?.region &&
    a.place?.country === b.place?.country
  );
}
