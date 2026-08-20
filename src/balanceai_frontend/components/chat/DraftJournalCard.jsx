import { View, Text } from 'react-native';
import { useTheme } from '../../theme';
import { Card } from '../Card';
import { TextField } from '../TextField';
import { Button } from '../Button';
import { Kicker } from './AssistantMessage';

const FIELDS = [
  { key: 'date', label: 'Date' },
  { key: 'merchant', label: 'Merchant' },
  { key: 'amount', label: 'Amount' },
  { key: 'category', label: 'Category' },
  { key: 'memo', label: 'Memo' },
];

export function DraftJournalCard({ intro, fields, onChangeField, onConfirm, onDiscard }) {
  const t = useTheme();

  return (
    <View>
      <Kicker />
      <Text style={{ fontFamily: t.fontBody, fontSize: 16, lineHeight: 24, color: t.text, maxWidth: 290, marginBottom: 12 }}>
        {intro}
      </Text>
      <Card elevation="sm" style={{ gap: 0, padding: 14, paddingBottom: 12 }}>
        <Text style={{ fontFamily: t.fontBody, fontSize: 10, letterSpacing: 1, textTransform: 'uppercase', color: t.neutral[700], marginBottom: 8 }}>
          Draft journal entry
        </Text>
        {FIELDS.map((f) => (
          <View key={f.key} style={{ flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 5 }}>
            <Text style={{ width: 74, fontFamily: t.fontBody, fontSize: 12, color: t.neutral[700] }}>{f.label}</Text>
            <TextField
              value={fields[f.key]}
              onChangeText={(v) => onChangeField(f.key, v)}
              style={{ flex: 1, backgroundColor: t.bg }}
            />
          </View>
        ))}
        <View style={{ flexDirection: 'row', gap: 8, marginTop: 12 }}>
          <Button variant="primary" onPress={onConfirm} style={{ flex: 1 }}>Confirm & post</Button>
          <Button variant="secondary" onPress={onDiscard}>Discard</Button>
        </View>
      </Card>
    </View>
  );
}
