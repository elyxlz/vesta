declare module "tz-lookup" {
  // (latitude, longitude) -> the IANA timezone id the point falls in, from an embedded offline
  // boundary table. Throws RangeError on coordinates outside the valid range.
  export default function tzlookup(latitude: number, longitude: number): string;
}
