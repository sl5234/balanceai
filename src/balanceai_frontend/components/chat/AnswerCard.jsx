import { View, Text, Pressable } from 'react-native';
import { useTheme } from '../../theme';
import { Kicker } from './AssistantMessage';

export function AnswerCard({ label, value, note, bars, link, onPressLink }) {
  const t = useTheme();

  return (
    <View>
      <Kicker />
      <View style={{ height: 3, backgroundColor: t.text, marginTop: 3 }} />
      <View style={{ height: 1, backgroundColor: t.text, marginTop: 2 }} />
      <Text style={{ fontFamily: t.fontBody, fontSize: 11, letterSpacing: 0.9, textTransform: 'uppercase', color: t.neutral[700], marginTop: 9 }}>
        {label}
      </Text>
      <Text style={{ fontFamily: t.fontHeading, fontWeight: '600', fontSize: 52, lineHeight: 50, letterSpacing: -1.6, color: t.text, marginTop: 2 }}>
        {value}
      </Text>
      <View style={{ flexDirection: 'row', alignItems: 'flex-end', gap: 14, marginTop: 10 }}>
        <Text style={{ flex: 1, fontFamily: t.fontBody, fontSize: 14, lineHeight: 20, color: t.neutral[800] }}>{note}</Text>
        <View style={{ flexDirection: 'row', alignItems: 'flex-end', gap: 3, height: 34 }}>
          {bars.map((b, i) => (
            <View
              key={i}
              style={{
                width: 9,
                height: `${b.h}%`,
                backgroundColor: b.tone === 500 ? t.accentRamp[500] : t.accentRamp[200],
              }}
            />
          ))}
        </View>
      </View>
      <Pressable onPress={onPressLink} style={{ marginTop: 10, alignSelf: 'flex-start' }}>
        <Text style={{ fontFamily: t.fontBody, fontSize: 14, color: t.accent }}>{link} →</Text>
      </Pressable>
    </View>
  );
}
