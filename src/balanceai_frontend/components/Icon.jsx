import { ChatsCircleIcon, BookOpenTextIcon, ChartPieSliceIcon, CameraIcon, PlusCircleIcon, ImagesIcon } from 'phosphor-react-native';

const ICONS = {
  chat: ChatsCircleIcon,
  ledger: BookOpenTextIcon,
  reports: ChartPieSliceIcon,
  camera: CameraIcon,
  'plus-circle': PlusCircleIcon,
  photos: ImagesIcon,
};

export function Icon({ name, size = 20, color = '#201e1d', weight = 'duotone' }) {
  const Cmp = ICONS[name];
  if (!Cmp) return null;
  return <Cmp size={size} color={color} weight={weight} />;
}
