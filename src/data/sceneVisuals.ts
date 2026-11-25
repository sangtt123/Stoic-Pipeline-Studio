export type VisualThemeKey =
  | 'betrayal_whispers'
  | 'anger_control'
  | 'walk_away_silence'
  | 'storm_helm'
  | 'deep_focus'
  | 'morning_discipline'
  | 'rebuild_failure'
  | 'career_pressure'
  | 'time_hourglass'
  | 'inner_citadel';

export interface SceneVisualAsset {
  key: VisualThemeKey;
  label: string;
  description: string;
  imageUrl: string;
}

export const SCENE_VISUAL_CATALOG: SceneVisualAsset[] = [
  {
    key: 'betrayal_whispers',
    label: 'Phản bội & Thị phi sau lưng',
    description: 'Người đàn ông giữ khí chất điềm tĩnh giữa những bóng người bàn tán, chỉ trỏ phía sau',
    imageUrl: '/src/assets/images/stoic_scene_betrayal_1795361954547.jpg',
  },
  {
    key: 'anger_control',
    label: 'Kiểm soát cơn giận & Nội tâm',
    description: 'Bàn tay đang siết chặt dần buông lỏng thành lòng bàn tay mở bên ngọn nến tĩnh lặng giữa mưa gió',
    imageUrl: '/src/assets/images/stoic_scene_anger_control_1795361953250.jpg',
  },
  {
    key: 'walk_away_silence',
    label: 'Rời đi trong im lặng & Ranh giới',
    description: 'Bước đi vững vàng rời khỏi căn phòng hỗn loạn hướng về cánh cửa ánh bình minh',
    imageUrl: '/src/assets/images/stoic_scene_walk_away_1795361953376.jpg',
  },
  {
    key: 'storm_helm',
    label: 'Vững tay lái giữa bão tố',
    description: 'Người cầm lái kiên định giữa sóng dữ và bóng tối, nhìn thẳng về ngọn hải đăng phía trước',
    imageUrl: '/src/assets/images/stoic_scene_storm_dark_1795362007057.jpg',
  },
  {
    key: 'deep_focus',
    label: 'Tập trung sâu & Nhật ký tĩnh lặng',
    description: 'Bàn làm việc tối giản với sổ tay, bút mực dưới ánh đèn ấm, điện thoại úp mặt xa góc tối',
    imageUrl: '/src/assets/images/stoic_scene_deep_focus_1795361976713.jpg',
  },
  {
    key: 'morning_discipline',
    label: 'Kỷ luật 5h sáng & Tự lập',
    description: 'Dáng người đứng thẳng trên ban công tĩnh lặng nhìn thành phố mờ sương lúc bình minh 5 giờ sáng',
    imageUrl: '/src/assets/images/stoic_scene_morning_discipline_1795361976511.jpg',
  },
  {
    key: 'rebuild_failure',
    label: 'Đứng dậy & Tái thiết sau thất bại',
    description: 'Kiên nhẫn đặt từng khối đá nền móng mới giữa những trụ đá đổ nát để xây lại từ đầu',
    imageUrl: '/src/assets/images/stoic_scene_rebuild_failure_1795361977494.jpg',
  },
  {
    key: 'career_pressure',
    label: 'Tâm bất động giữa áp lực sự nghiệp',
    description: 'Ngồi ngay ngắn bình tĩnh giữa vòng xoáy giấy tờ, đồng hồ và biến động tài chính xung quanh',
    imageUrl: '/src/assets/images/stoic_scene_career_pressure_1795361980643.jpg',
  },
  {
    key: 'time_hourglass',
    label: 'Thời gian hữu hạn (Memento Mori)',
    description: 'Đồng hồ cát cổ điển khắc họa giá trị từng khoảnh khắc không thể quay lại',
    imageUrl: '/src/assets/images/stoic_scene_hourglass_1795345801132.jpg',
  },
  {
    key: 'inner_citadel',
    label: 'Thành trì nội tâm vững chãi',
    description: 'Hàng cột đá cổ điển biểu tượng cho sự bền vững tinh thần trước thử thách thời gian',
    imageUrl: '/src/assets/images/stoic_scene_temple_1795345802062.jpg',
  },
];

export const SCENE_VISUAL_MAP: Record<VisualThemeKey, SceneVisualAsset> =
  SCENE_VISUAL_CATALOG.reduce((acc, item) => {
    acc[item.key] = item;
    return acc;
  }, {} as Record<VisualThemeKey, SceneVisualAsset>);

export function resolveSceneVisual(
  requestedKey: string | undefined,
  usedKeys: Set<VisualThemeKey>
): SceneVisualAsset {
  const normalized = (requestedKey || '').trim() as VisualThemeKey;
  if (normalized in SCENE_VISUAL_MAP && !usedKeys.has(normalized)) {
    usedKeys.add(normalized);
    return SCENE_VISUAL_MAP[normalized];
  }
  const unused = SCENE_VISUAL_CATALOG.find((item) => !usedKeys.has(item.key));
  const picked = unused ?? SCENE_VISUAL_CATALOG[0];
  usedKeys.add(picked.key);
  return picked;
}

export const STUDIO_TOPIC_PRESETS = [
  {
    label: 'Phản bội & Công kích',
    philosopher: 'Marcus Aurelius',
    topicVi: 'Nghệ thuật giữ bình tĩnh tuyệt đối khi bị phản bội và công kích sau lưng',
    topicEn: 'The art of unshakable calm when betrayed and attacked behind your back',
  },
  {
    label: 'Kiểm soát cơn giận & Áp lực',
    philosopher: 'Seneca',
    topicVi: 'Cách làm chủ cơn giận và giữ đầu lạnh giữa áp lực sự nghiệp, tài chính',
    topicEn: 'How to master anger and stay centered under intense career and financial pressure',
  },
  {
    label: 'Tái thiết sau thất bại & Kỷ luật',
    philosopher: 'Epictetus',
    topicVi: 'Đứng dậy từ con số không bằng kỷ luật 5 giờ sáng và sự tập trung tuyệt đối',
    topicEn: 'Rebuilding from zero through 5 AM discipline and ruthless deep focus',
  },
];
