import { View, Text, Pressable } from 'react-native';
import { useTheme } from '../../theme';

export function ChipList({ chips }) {
  const t = useTheme();
  return (
    <View style={{ alignItems: 'flex-start', gap: 8 }}>
      {chips.map((c, i) => (
        <Pressable
          key={i}
          onPress={c.onPress}
          style={({ pressed }) => ({
            borderWidth: 1,
            borderColor: t.accent,
            borderRadius: 1.5,
            paddingVertical: 7,
            paddingHorizontal: 12,
            backgroundColor: pressed ? t.accentRamp[100] : 'transparent',
          })}
        >
          <Text style={{ fontFamily: t.fontBody, fontSize: 13, lineHeight: 17, color: t.accent }}>{c.text}</Text>
        </Pressable>
      ))}
    </View>
  );
}
