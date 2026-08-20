import { View, Text } from 'react-native';
import { useTheme } from '../theme';

export function Avatar({ initials, size = 28 }) {
  const t = useTheme();
  return (
    <View style={{
      width: size, height: size, borderRadius: size / 2,
      backgroundColor: t.accentRamp[200],
      alignItems: 'center', justifyContent: 'center',
    }}>
      <Text style={{ fontFamily: t.fontHeading, fontWeight: '600', fontSize: 12, color: t.accentRamp[800] }}>{initials}</Text>
    </View>
  );
}
