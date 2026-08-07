export function shouldAcceptComposerTextChange(
  interactive: boolean,
  currentValue: string,
  nextValue: string,
): boolean {
  return interactive || nextValue === currentValue;
}
