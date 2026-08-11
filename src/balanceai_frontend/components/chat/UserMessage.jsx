import { View, Text } from 'react-native';
import { useTheme } from '../../theme';

export function UserMessage({ text }) {
  const t = useTheme();
  return (
    <View style={{ alignItems: 'flex-end' }}>
      <View style={{ backgroundColor: t.surface, borderRadius: t.radius.md, paddingVertical: 9, paddingHorizontal: 13, maxWidth: 250 }}>
        <Text style={{ fontFamily: t.fontBody, fontSize: 15, lineHeight: 22, color: t.text }}>{text}</Text>
      </View>
    </View>
  );
}
