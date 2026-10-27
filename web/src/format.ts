/** `java.lang.NullPointerException` -> `NullPointerException`, `Solution$Node` -> `Node`. */
export function shortType(type: string): string {
  return type.split('.').pop()!.split('$').pop()!
}
