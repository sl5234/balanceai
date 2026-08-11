import { View, Text, Pressable, Modal } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '../../theme';

const GROUND = '#141312';
const PAPER = '#f3f2f2';

export function CameraOverlay({ visible, onClose, onShoot }) {
  const t = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="fullScreen" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: GROUND }}>
        <View style={{ paddingTop: Math.max(insets.top, 16), paddingHorizontal: 18 }}>
          <Pressable onPress={onClose}>
            <Text style={{ color: PAPER, fontFamily: t.fontBody, fontSize: 15 }}>← Chat</Text>
          </Pressable>
        </View>

        <View style={{
          flex: 1, margin: 14, marginHorizontal: 18,
          borderWidth: 1, borderColor: 'rgba(243,242,242,0.35)',
          alignItems: 'center', justifyContent: 'center',
          backgroundColor: '#1d1c1b',
        }}>
          <Text style={{ fontFamily: t.monoLabel, fontSize: 11, color: 'rgba(243,242,242,0.55)', textAlign: 'center' }}>
            viewfinder{'\n'}frame the receipt
          </Text>
        </View>

        <View style={{ paddingHorizontal: 18, paddingBottom: Math.max(insets.bottom, 44), alignItems: 'center' }}>
          <Pressable
            onPress={onShoot}
            style={{
              width: 66, height: 66, borderRadius: 33,
              backgroundColor: PAPER,
              borderWidth: 4, borderColor: 'rgba(243,242,242,0.4)',
            }}
          />
        </View>
      </View>
    </Modal>
  );
}
