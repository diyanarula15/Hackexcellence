// GeoNames WGS84 anchors. Region/island records are explicitly marked as
// destination approximations so a pin does not imply an exact city coordinate.
export const cityAnchors = {
  JP: {
    Tokyo: { coordinates: [139.69171, 35.6895], label: 'Tokyo', geonameId: 1850147 },
    Kyoto: { coordinates: [135.75385093689, 35.02106999142], label: 'Kyoto', geonameId: 1857910 },
    Osaka: { coordinates: [135.50107, 34.69379], label: 'Osaka', geonameId: 1853909 },
  },
  AE: {
    Dubai: { coordinates: [55.30927, 25.07725], label: 'Dubai', geonameId: 292223 },
    'Abu Dhabi': { coordinates: [54.396958, 24.451185], label: 'Abu Dhabi', geonameId: 292968 },
  },
  TH: {
    Bangkok: { coordinates: [100.501444, 13.753979], label: 'Bangkok', geonameId: 1609350 },
    Phuket: { coordinates: [98.3981037139893, 7.89058847415623], label: 'Phuket', sourceType: 'GeoNames place search' },
    'Chiang Mai': { coordinates: [98.984683, 18.790376], label: 'Chiang Mai', geonameId: 1153671 },
  },
  SG: {
    Singapore: { coordinates: [103.850069046021, 1.28966883937733], label: 'Singapore', geonameId: 1880252 },
  },
  MY: {
    'Kuala Lumpur': { coordinates: [101.68653, 3.14309], label: 'Kuala Lumpur', geonameId: 1733046 },
    Penang: {
      coordinates: [100.25848, 5.37677],
      label: 'Penang destination anchor (GeoNames region point)',
      geonameId: 1733047,
      approximate: true,
    },
    Langkawi: {
      coordinates: [99.78375, 6.35608],
      label: 'Langkawi destination anchor (GeoNames region point)',
      sourceType: 'GeoNames place search',
      approximate: true,
    },
  },
  ID: {
    Bali: {
      coordinates: [115, -8.33333],
      label: 'Bali island anchor',
      geonameId: 1650534,
      approximate: true,
    },
    Jakarta: { coordinates: [106.84513092041016, -6.214623197035775], label: 'Jakarta', sourceType: 'GeoNames place search' },
    Yogyakarta: { coordinates: [110.364722, -7.801389], label: 'Yogyakarta', sourceType: 'GeoNames place search' },
  },
  VN: {
    Hanoi: { coordinates: [105.8411693572998, 21.02450477127423], label: 'Hanoi', geonameId: 1581130 },
    'Da Nang': { coordinates: [108.220833, 16.067778], label: 'Da Nang', geonameId: 1583992 },
    'Ho Chi Minh City': { coordinates: [106.62965, 10.82302], label: 'Ho Chi Minh City', geonameId: 1566083 },
  },
};
