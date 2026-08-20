import { View, Text } from 'react-native';
import { useTheme } from '../../theme';

export function Kicker() {
  const t = useTheme();
  return (
    <Text style={{ fontFamily: t.fontBody, fontSize: 10, letterSpacing: 1, textTransform: 'uppercase', marginBottom: 5 }}>
      <Text style={{ color: t.accent }}>Balance</Text>
      <Text style={{ color: t.accent2 }}>AI</Text>
    </Text>
  );
}

export function AssistantMessage({ text }) {
  const t = useTheme();
  return (
    <View>
      <Kicker />
      <Text style={{ fontFamily: t.fontBody, fontSize: 16, lineHeight: 24, color: t.text, maxWidth: 290 }}>{text}</Text>
    </View>
  );
}
