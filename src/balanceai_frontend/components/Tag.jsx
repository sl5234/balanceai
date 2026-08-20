import { View, Text } from 'react-native';
import { useTheme } from '../theme';

export function Tag({ children, variant = 'accent' }) {
  const t = useTheme();

  const styles = {
    accent: { backgroundColor: t.accentRamp[100], color: t.accentRamp[800], borderWidth: 0 },
    accent2: { backgroundColor: t.accent2Ramp[100], color: t.accent2Ramp[800], borderWidth: 0 },
    neutral: { backgroundColor: t.neutral[100], color: t.neutral[800], borderWidth: 0 },
    outline: { backgroundColor: 'transparent', color: t.accent, borderWidth: 1, borderColor: t.accent },
  };
  const s = styles[variant] ?? styles.accent;

  return (
    <View style={{
      alignSelf: 'flex-start',
      backgroundColor: s.backgroundColor,
      borderWidth: s.borderWidth,
      borderColor: s.borderColor,
      borderRadius: t.radius.md * 0.75,
      paddingVertical: 3,
      paddingHorizontal: 10,
    }}>
      <Text style={{ fontFamily: t.fontBody, fontSize: 11, letterSpacing: 0.2, color: s.color }}>{children}</Text>
    </View>
  );
}
