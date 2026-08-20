import { View, Text, Image } from 'react-native';
import { useTheme } from '../../theme';

export function ReceiptPlaceholder({ width, height }) {
  const t = useTheme();
  return (
    <View style={{
      width, height,
      borderRadius: t.radius.md,
      backgroundColor: t.neutral[200],
      borderWidth: 1,
      borderColor: t.neutral[300],
      alignItems: 'center',
      justifyContent: 'center',
    }}>
      <Text style={{ fontFamily: t.monoLabel, fontSize: 10, color: t.neutral[600], textAlign: 'center' }}>
        receipt{'\n'}photo
      </Text>
    </View>
  );
}

export function PhotoMessage({ uri }) {
  const t = useTheme();
  return (
    <View style={{ alignItems: 'flex-end' }}>
      {uri ? (
        <Image
          source={{ uri }}
          style={{ width: 150, height: 196, borderRadius: t.radius.md }}
          resizeMode="cover"
        />
      ) : (
        <ReceiptPlaceholder width={150} height={196} />
      )}
    </View>
  );
}
