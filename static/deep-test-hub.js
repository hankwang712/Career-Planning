/* deep-test-hub.js — 趣味测试 & 深层探索模块
 * 包含：老友记角色测试 / 脑筋急转弯情绪测试 / 深层 MBTI 52 题测评 + AI 分析
 */
(function () {

  /* ====================================================
   * 一、数据层
   * ==================================================== */

  // 深层 MBTI — 52 道 5 档量表题（源自 trueyouteller，已翻译为中文）
  // dir: 1 → 偏向 E/N/F/P；dir: -1 → 偏向 I/S/T/J
  const DEEP_Q = [
    { id: 1,  text: "在大型社交聚会上，我感到精力充沛。",             axis: "IE", dir:  1 },
    { id: 2,  text: "做重要决定时，我主要依靠逻辑分析和事实。",       axis: "TF", dir: -1 },
    { id: 3,  text: "我喜欢把大量空闲时间独自用于追求个人兴趣。",     axis: "IE", dir: -1 },
    { id: 4,  text: "开始新项目之前，我倾向于制定明确的计划和结构。", axis: "JP", dir: -1 },
    { id: 5,  text: "我能很快适应意外变化，随机应变。",               axis: "JP", dir:  1 },
    { id: 6,  text: "我喜欢进行关于抽象概念的深入哲学讨论。",         axis: "SN", dir:  1 },
    { id: 7,  text: "繁忙的一周后，我倾向于在安静、熟悉的环境中放松。", axis: "IE", dir: -1 },
    { id: 8,  text: "即使可能引起争议，我也倾向于直接坦率地表达自己的想法。", axis: "TF", dir: -1 },
    { id: 9,  text: "我是一个极富创造力和想象力的人。",               axis: "SN", dir:  1 },
    { id: 10, text: "保持可预测的日常规律对我的身心健康很重要。",     axis: "JP", dir: -1 },
    { id: 11, text: "我经常发现自己在担忧未来可能发生的事情。",       axis: "SN", dir:  1 },
    { id: 12, text: "为了实现目标，我愿意承担一定的风险。",           axis: "JP", dir:  1 },
    { id: 13, text: "我善于设身处地理解他人的感受和情绪。",           axis: "TF", dir:  1 },
    { id: 14, text: "我更喜欢关注实际事务，而非理论概念。",           axis: "SN", dir: -1 },
    { id: 15, text: "我是一个井井有条、做事有条理的人。",             axis: "JP", dir: -1 },
    { id: 16, text: "我喜欢成为大家关注的中心。",                     axis: "IE", dir:  1 },
    { id: 17, text: "我重视和谐，并努力避免冲突和争执。",             axis: "TF", dir:  1 },
    { id: 18, text: "他人犯错时，我很容易原谅他们。",                 axis: "TF", dir:  1 },
    { id: 19, text: "我被取得实质性成果和成功所激励。",               axis: "SN", dir: -1 },
    { id: 20, text: "我经常反思自己过去的经历并从中汲取教训。",       axis: "SN", dir:  1 },
    { id: 21, text: "我发现与陌生人开始对话很容易。",                 axis: "IE", dir:  1 },
    { id: 22, text: "我是一个注重细节的人。",                         axis: "SN", dir: -1 },
    { id: 23, text: "我对批评比较敏感。",                             axis: "TF", dir:  1 },
    { id: 24, text: "我喜欢探索新颖的、非传统的想法。",               axis: "SN", dir:  1 },
    { id: 25, text: "我倾向于完全完成一项任务后，再开始另一项。",     axis: "JP", dir: -1 },
    { id: 26, text: "我对未来普遍持乐观积极的态度。",                 axis: "IE", dir:  1 },
    { id: 27, text: "我发现说服他人接受我的观点很容易。",             axis: "TF", dir: -1 },
    { id: 28, text: "我是一个善于倾听的人。",                         axis: "TF", dir:  1 },
    { id: 29, text: "我倾向于一步一步解决问题，而非着眼于整体大局。", axis: "SN", dir: -1 },
    { id: 30, text: "我在压力下工作时感到自如。",                     axis: "JP", dir:  1 },
    { id: 31, text: "我喜欢为他人计划和组织各种活动。",               axis: "IE", dir:  1 },
    { id: 32, text: "如果没有足够的刺激和新鲜感，我很容易感到无聊。", axis: "JP", dir:  1 },
    { id: 33, text: "我非常关心社会公正问题。",                       axis: "TF", dir:  1 },
    { id: 34, text: "比起“如何做”，我更对事物背后的“为什么”感兴趣。", axis: "SN", dir:  1 },
    { id: 35, text: "我善于有效管理自己的时间。",                     axis: "JP", dir: -1 },
    { id: 36, text: "我喜欢认识来自不同背景的新朋友。",               axis: "IE", dir:  1 },
    { id: 37, text: "我倾向于避免对抗性的场面。",                     axis: "TF", dir:  1 },
    { id: 38, text: "我对他人很有耐心。",                             axis: "TF", dir:  1 },
    { id: 39, text: "我有动力在所做的一切事情中追求卓越。",           axis: "JP", dir: -1 },
    { id: 40, text: "我通过动手实践来学习，效果比读书或听讲好。",     axis: "SN", dir: -1 },
    { id: 41, text: "我能轻松地公开表达自己的情感。",                 axis: "TF", dir:  1 },
    { id: 42, text: "我会注意到他人可能忽略的细节。",                 axis: "SN", dir: -1 },
    { id: 43, text: "我会把批评当成针对个人的事情。",                 axis: "TF", dir:  1 },
    { id: 44, text: "我对需要抽象思维的复杂问题很感兴趣。",           axis: "SN", dir:  1 },
    { id: 45, text: "我宁可保持更多的选项，也不愿过早做出明确决定。", axis: "JP", dir:  1 },
    { id: 46, text: "我喜欢领导团队或小组。",                         axis: "IE", dir:  1 },
    { id: 47, text: "我对正在挣扎中的人充满同情心。",                 axis: "TF", dir:  1 },
    { id: 48, text: "我善于找到问题的实际可行的解决方案。",           axis: "SN", dir: -1 },
    { id: 49, text: "我能接受不确定性和模棱两可的情况。",             axis: "JP", dir:  1 },
    { id: 50, text: "我在工作中追求完美。",                           axis: "JP", dir: -1 },
    { id: 51, text: "我经常主动发起话题或活动。",                     axis: "IE", dir:  1 },
    { id: 52, text: "我更相信直觉和灵感，而不是经验和数据。",         axis: "SN", dir:  1 },
  ];

  const DEEP_ANSWERS = [
    { value: -2, label: "强烈不同意" },
    { value: -1, label: "不同意"     },
    { value:  0, label: "中立"       },
    { value:  1, label: "同意"       },
    { value:  2, label: "强烈同意"   },
  ];

  const MBTI_NAMES = {
    INTJ:"建筑师", INTP:"逻辑学家", ENTJ:"指挥官", ENTP:"辩论者",
    INFJ:"提倡者", INFP:"调停者",   ENFJ:"主人公", ENFP:"竞选者",
    ISTJ:"物流师", ISFJ:"守卫者",   ESTJ:"总经理", ESFJ:"执政官",
    ISTP:"鉴赏家", ISFP:"探险家",   ESTP:"企业家", ESFP:"表演者",
  };

  // ——— 16 型完整人格详情（来自 trueyouteller，保留英文内容） ———
  // MBTI_DETAIL loaded lazily from mbti_detail.json (extracted to reduce parse time)
  let _mbtiDetailCache = null;
  async function _loadMbtiDetail() {
    if (_mbtiDetailCache) return _mbtiDetailCache;
    try {
      const res = await fetch("/static/mbti_detail.json");
      _mbtiDetailCache = await res.json();
    } catch(e) { _mbtiDetailCache = {}; }
    return _mbtiDetailCache;
  }


  const MBTI_EMOJI = {
    INTJ:"🏛️", INTP:"🔭", ENTJ:"⚡", ENTP:"💡",
    INFJ:"🌟", INFP:"🎨", ENFJ:"🌍", ENFP:"🎪",
    ISTJ:"📋", ISFJ:"🛡️", ESTJ:"📊", ESFJ:"🤝",
    ISTP:"🔧", ISFP:"🌸", ESTP:"🎯", ESFP:"🎭",
  };

  // ——— 老友记角色测试 ———
  const FRIENDS_Q = [
    { id:1,  text:"在咖啡馆，你常坐的沙发被占了，你会怎么做？",
      opts:[{t:"耐心等待",v:"A"},{t:"尝试说服对方",v:"B"},{t:"另找位置坐",v:"C"},{t:"直接离开",v:"D"}] },
    { id:2,  text:"感恩节大餐搞砸了，你的第一反应是？",
      opts:[{t:"立刻动手补救，一定要完美",v:"A"},{t:"讲几个笑话缓和气氛",v:"B"},{t:"主动帮忙，虽然不太会",v:"C"},{t:"安静地等结果",v:"D"}] },
    { id:3,  text:"搬重家具时，你的策略是？",
      opts:[{t:"大喊“PIVOT！”",v:"A"},{t:"一个人扛上去",v:"B"},{t:"用非常规方法",v:"C"},{t:"在旁边指挥",v:"D"}] },
    { id:4,  text:"理想的周五晚上？",
      opts:[{t:"安静地窝在家里",v:"A"},{t:"出去认识新朋友",v:"B"},{t:"做一顿丰盛大餐",v:"C"},{t:"大声看体育比赛",v:"D"}] },
    { id:5,  text:"如何应对难相处的室友？",
      opts:[{t:"逻辑地分析谈判",v:"A"},{t:"贴被动攻击式便利贴",v:"B"},{t:"设计一个精心的小计谋",v:"C"},{t:"直接当面摊牌",v:"D"}] },
    { id:6,  text:"你和食物的关系？",
      opts:[{t:"食物是一门精准的艺术",v:"A"},{t:"热爱食物，从不分享",v:"B"},{t:"通过美食表达爱意",v:"C"},{t:"注重健康和均衡",v:"D"}] },
    { id:7,  text:"你的个人风格是？",
      opts:[{t:"时尚前沿，紧跟潮流",v:"A"},{t:"舒适实用，不在意形象",v:"B"},{t:"独特个性，不走寻常路",v:"C"},{t:"随手拿什么穿什么",v:"D"}] },
    { id:8,  text:"听到八卦，你通常会？",
      opts:[{t:"立刻想知道所有细节",v:"A"},{t:"尝试从中调解",v:"B"},{t:"觉得无聊，不感兴趣",v:"C"},{t:"从社会学角度分析",v:"D"}] },
    { id:9,  text:"计划一次旅行，第一步是？",
      opts:[{t:"制定详细行程表",v:"A"},{t:"先想和谁去",v:"B"},{t:"找一个奇特的目的地",v:"C"},{t:"规划最合理的交通路线",v:"D"}] },
    { id:10, text:"你的口头禅最接近？",
      opts:[{t:"我难道不能更……吗？",v:"A"},{t:"你……还好吗？",v:"B"},{t:"臭猫咪，臭猫咪……",v:"C"},{t:"我知道！",v:"D"}] },
  ];

  // 每道题选项 → 得分的角色列表
  const FRIENDS_SCORE = {
    1:{A:["Ross","Monica"],   B:["Joey","Rachel"],  C:["Chandler"],       D:["Phoebe"]},
    2:{A:["Monica"],          B:["Chandler"],       C:["Joey","Phoebe"],  D:["Ross"]},
    3:{A:["Ross"],            B:["Monica"],         C:["Phoebe"],         D:["Rachel"]},
    4:{A:["Ross","Monica"],   B:["Joey","Rachel"],  C:["Monica"],         D:["Joey"]},
    5:{A:["Ross"],            B:["Chandler"],       C:["Joey","Phoebe"],  D:["Monica"]},
    6:{A:["Monica"],          B:["Joey"],           C:["Phoebe"],         D:["Ross"]},
    7:{A:["Rachel"],          B:["Joey"],           C:["Phoebe"],         D:["Chandler"]},
    8:{A:["Rachel","Joey"],   B:["Monica"],         C:["Chandler"],       D:["Ross"]},
    9:{A:["Monica"],          B:["Joey"],           C:["Phoebe"],         D:["Ross"]},
   10:{A:["Chandler"],        B:["Joey"],           C:["Phoebe"],         D:["Monica"]},
  };

  const FRIENDS_RESULTS = {
    Ross:    { name:"罗斯",    emoji:"🦕", color:"#7c6fcd",
      tagline:"PIVOT！PIVOT！PIVOT！",
      synopsis:"罗斯是一位充满热情的古生物学家，有点社恐但内心细腻丰富。他是个浪漫主义者，对自己热爱的事物极度执着，有时会因计划受阻而上演戏剧性崩溃。",
      traits:["过度分析各种情况，甚至到了荒谬的程度","对自己的热情领域（恐龙！）有深厚的热爱","当事情不按计划进行时，容易引发令人发笑的崩溃"],
      compatible:["钱德勒·宾","莫妮卡·盖勒"] },
    Joey:    { name:"乔伊",    emoji:"🍕", color:"#e8a44a",
      tagline:"你……还好吗？",
      synopsis:"乔伊是个可爱、单纯、永远处于饥饿状态的演员。他极度忠诚，魅力十足，把食物和友谊置于一切之上，常常对复杂局面浑然不觉。",
      traits:["对食物有深厚的热爱，尤其是三明治，强烈抵制分享","仅靠一句简单的开场白就能迷倒所有人","忠诚是他的第一优先级，永远站在朋友这边"],
      compatible:["钱德勒·宾","菲比·布菲"] },
    Phoebe:  { name:"菲比",    emoji:"🎸", color:"#66bb6a",
      tagline:"臭猫咪，臭猫咪……",
      synopsis:"菲比是个古灵精怪、自由不羁、极度忠诚的存在。她按照自己的规则生活，拥抱个人怪癖，提供非常规但有时很深刻的人生智慧。",
      traits:["会突然唱起即兴创作的歌，通常是关于猫或个人奇遇","提供异想天开的建议，但有时出奇地深刻","有着独一无二、令人难忘的个人风格"],
      compatible:["乔伊·托里亚尼","瑞秋·格林"] },
    Monica:  { name:"莫妮卡",  emoji:"🍳", color:"#ef5350",
      tagline:"欢迎来到真实世界！",
      synopsis:"莫妮卡是那个有组织、有竞争心、忠诚无比的大厨。她热爱做东道主，对整洁和完美有执念，总是把一切都变成竞赛。",
      traits:["对清洁和秩序有强迫症般的追求","极度好胜，什么事都能变成比赛","烹饪和待客是她的天赋，总要确保所有人吃饱喝足"],
      compatible:["钱德勒·宾","罗斯·盖勒"] },
    Chandler:{ name:"钱德勒",  emoji:"😅", color:"#42a5f5",
      tagline:"我是个绝望、笨拙、渴望爱的人！",
      synopsis:"钱德勒是那个刻薄、机智、时常尴尬的朋友，习惯用幽默来掩盖不安全感。他对承诺有些困难，但对朋友无比忠诚。",
      traits:["用讽刺来转移不适或表达感情","在情绪化或严肃的场合会变得尴尬","自我贬低的笑话信手拈来"],
      compatible:["乔伊·托里亚尼","莫妮卡·盖勒"] },
    Rachel:  { name:"瑞秋",    emoji:"👗", color:"#ab47bc",
      tagline:"TA-DA！",
      synopsis:"瑞秋是那个充满活力、引领潮流、雄心勃勃的时尚达人。她从一个富家女成长为一个独立自主、事业心极强的女性。",
      traits:["对时尚有敏锐的感知力，永远光鲜靓丽","喜欢以戏剧性的方式登场或退场","对朋友极度忠诚，即使有时会做出奇怪的选择"],
      compatible:["菲比·布菲","乔伊·托里亚尼"] },
  };

  // ——— 头脑特工队情绪测试 ———
  const IO_Q = [
    { id:1,  text:"新学校/工作的第一天，你的感受是？",
      opts:[{t:"对新的可能性感到兴奋！",v:"Joy"},{t:"有点不知所措，很担心。",v:"Fear"},{t:"对各种变化感到烦躁。",v:"Anger"},{t:"感觉有点低落。",v:"Sadness"},{t:"对一切都有点挑剔。",v:"Disgust"}] },
    { id:2,  text:"朋友分享了一个坏消息，你的第一反应是？",
      opts:[{t:"寻找积极的一面，给他们加油打气。",v:"Joy"},{t:"提供安慰，认真倾听。",v:"Sadness"},{t:"立刻追问是谁造成了这个问题。",v:"Anger"},{t:"开始担心所有潜在的负面结果。",v:"Fear"},{t:"对这种情况表示不满。",v:"Disgust"}] },
    { id:3,  text:"宅家看电影，你会选？",
      opts:[{t:"励志喜剧或冒险片。",v:"Joy"},{t:"发人深省的剧情片。",v:"Sadness"},{t:"紧张刺激的动作惊悚片。",v:"Anger"},{t:"不太恐怖或不安的任何片。",v:"Fear"},{t:"获奖佳片，不看烂片。",v:"Disgust"}] },
    { id:4,  text:"计划突然改变，你怎么反应？",
      opts:[{t:"享受这种随机性，找到新乐趣。",v:"Joy"},{t:"感到一阵失落。",v:"Sadness"},{t:"感到沮丧，有点急躁。",v:"Anger"},{t:"对未知产生焦虑。",v:"Fear"},{t:"翻个白眼，觉得很麻烦。",v:"Disgust"}] },
    { id:5,  text:"你最大的烦恼是？",
      opts:[{t:"负能量把大家都带跑偏了。",v:"Joy"},{t:"感觉被误解或不被倾听。",v:"Sadness"},{t:"不公平和不公正。",v:"Anger"},{t:"不必要的冒险或不安全的情况。",v:"Fear"},{t:"低俗品味或不礼貌的行为。",v:"Disgust"}] },
    { id:6,  text:"面对一个新挑战，你怎么处理？",
      opts:[{t:"带着乐观和决心迎难而上。",v:"Joy"},{t:"谨慎地考虑所有可能的挫折。",v:"Sadness"},{t:"主动出击，准备正面硬刚。",v:"Anger"},{t:"做全面的风险评估再行动。",v:"Fear"},{t:"只有在达到我的高标准时才参与。",v:"Disgust"}] },
    { id:7,  text:"有人对你说了粗鲁的话，你的回应？",
      opts:[{t:"试着大事化小，保持积极。",v:"Joy"},{t:"感到受伤，可能会退缩。",v:"Sadness"},{t:"立刻用一句话怼回去。",v:"Anger"},{t:"开始担心更多的冲突会来。",v:"Fear"},{t:"投以鄙视的眼神。",v:"Disgust"}] },
    { id:8,  text:"你的日常穿搭？",
      opts:[{t:"明亮、欢快的色调。",v:"Joy"},{t:"舒适、慵懒系。",v:"Sadness"},{t:"干练、有气场。",v:"Anger"},{t:"实用、安全第一。",v:"Fear"},{t:"时髦且无可挑剔。",v:"Disgust"}] },
    { id:9,  text:"看到一个错误正在发生，你会？",
      opts:[{t:"找到一个创意方式来纠正它。",v:"Joy"},{t:"温和地指出问题，关心他人感受。",v:"Sadness"},{t:"直接上去，立刻搞定。",v:"Anger"},{t:"迟疑，害怕把事情弄得更糟。",v:"Fear"},{t:"表达对这个错误的不满。",v:"Disgust"}] },
    { id:10, text:"什么样的记忆对你来说最核心？",
      opts:[{t:"纯粹的快乐和温暖。",v:"Joy"},{t:"深刻的情感深度。",v:"Sadness"},{t:"关于公正或公平的重要时刻。",v:"Anger"},{t:"让我学会避免危险的教训。",v:"Fear"},{t:"真实且高质量的时光。",v:"Disgust"}] },
    { id:11, text:"明天有个重要的演讲，你在想？",
      opts:[{t:"万一我搞砸了？我要再练100遍！",v:"Anxiety"},{t:"我很紧张，万一设备出问题怎么办。",v:"Fear"},{t:"我迫不及待想分享我的想法！",v:"Joy"},{t:"哎，一定要去吗……",v:"Ennui"}] },
    { id:12, text:"看到别人穿了你一直想要的单品，你想？",
      opts:[{t:"要是那是我就好了，他们看起来太棒了。",v:"Envy"},{t:"我可以搭配得比他们更好。",v:"Disgust"},{t:"他们看起来真的很好！太棒了！",v:"Joy"},{t:"我大概这辈子都没法驾驭那件衣服。",v:"Sadness"}] },
    { id:13, text:"在人群中不小心绊倒了，你会？",
      opts:[{t:"我的人生完了，我要就地消失。",v:"Embarrassment"},{t:"是谁把地板放在那里的！",v:"Anger"},{t:"哈哈，顺势鞠个躬。",v:"Joy"},{t:"哦不，大家都在看我吗？",v:"Fear"}] },
    { id:14, text:"大家在讨论去哪玩，你的意见是？",
      opts:[{t:"随便。（耸肩）",v:"Ennui"},{t:"我们来列一个每个方案的利弊清单。",v:"Anxiety"},{t:"快点定个地方！这也太慢了！",v:"Anger"},{t:"我们去做个超好玩的事情！",v:"Joy"}] },
  ];

  const IO_RESULTS = {
    Joy:          { name:"快乐",   emoji:"😊", color:"#FFD700",
      tagline:"来，制造一些核心记忆吧！",
      synopsis:"快乐是乐观积极的领导者，总是努力让身边的人保持快乐和正能量。她活力无限，能在任何情况下找到美好的一面。",
      traits:["即使在困难时期也能看到光明面","无尽的活力和热情，有时会让人招架不住","总想着把负面情绪变成正面的"],
      compatible:["悲伤","厌恶"] },
    Sadness:      { name:"悲伤",   emoji:"😢", color:"#6699CC",
      tagline:"感到悲伤也没关系。",
      synopsis:"悲伤是一种常被误解的情绪，她有着深厚的同理心和情感连接能力，帮助我们处理失去、获得他人的安慰与支持。",
      traits:["有放慢脚步、沉浸在感受中的倾向","深厚的同理心，善于安慰他人","有时感到被误解或低估"],
      compatible:["快乐","恐惧"] },
    Anger:        { name:"愤怒",   emoji:"😡", color:"#CC3300",
      tagline:"好，我要把这件事提升到下一个级别！",
      synopsis:"愤怒是热情而直接的情绪，迅速对不公正或挫折做出反应。他是保护者，确保公平、挺身而出，有时会爆发性出现。",
      traits:["倾向于对感知到的错误做出快速而直接的反应","被对公平和正义的渴望所驱动","当事情不顺心时，有时会真的冒火"],
      compatible:["恐惧","厌恶"] },
    Fear:         { name:"恐惧",   emoji:"😨", color:"#9966CC",
      tagline:"我们要死了！",
      synopsis:"恐惧是高度焦虑谨慎的情绪，不断评估风险，努力保持安全。他是一个细心的规划者，虽然有时过于极端。",
      traits:["对每一个可能的负面结果进行细致的规划","有过度担心的倾向，即使是小事","在新情况下不断评估风险和潜在危险"],
      compatible:["快乐","悲伤"] },
    Disgust:      { name:"厌恶",   emoji:"🤢", color:"#009900",
      tagline:"哎，随便吧，无所谓。",
      synopsis:"厌恶是那个时髦、有主见、高度挑剔的情绪，保护我们免受任何被认为是恶心、不酷或道德上有问题的东西的侵害。",
      traits:["对任何恶心、不吸引人或低俗的东西有强烈的厌恶感","快速、经常带有讽刺意味地判断各种情况","为自己和周围环境保持高标准"],
      compatible:["愤怒","快乐"] },
    Anxiety:      { name:"焦虑",   emoji:"😰", color:"#FF7F50",
      tagline:"我需要看看你的证明文件。",
      synopsis:"焦虑是一个高能量、注重细节的情绪，不断为潜在问题做规划，努力确保未来的安全。她被对每种可能情况的准备需求所驱动。",
      traits:["强迫性地制作清单和备用方案","快节奏、常常焦躁不安，被对未来的忧虑驱动","不断重演场景以识别潜在问题"],
      compatible:["恐惧","愤怒"] },
    Ennui:        { name:"厌倦",   emoji:"😒", color:"#808080",
      tagline:"无所谓。",
      synopsis:"厌倦以深刻的无聊感、冷漠和漠不关心为特征。他以超然、毫无印象的态度看待大多数情况，通常用手机作为不参与的屏障。",
      traits:["需要不断的娱乐，却很少被打动","对大多数情况的超然、近乎漠然的反应","经常被手机或其他个人设备分心"],
      compatible:["厌恶","悲伤"] },
    Embarrassment:{ name:"尴尬",   emoji:"😳", color:"#FFB6C1",
      tagline:"呃……糟糕？",
      synopsis:"尴尬是一种害羞且自我意识强的情绪，当社交尴尬场景出现时往往会退缩或躲藏。他对社交失误和个人失误非常敏感。",
      traits:["在尴尬时会脸红或想躲起来","事后过度思考社交互动","强烈渴望避免成为尴尬关注的焦点"],
      compatible:["悲伤","恐惧"] },
    Envy:         { name:"羡慕",   emoji:"😤", color:"#ADFF2F",
      tagline:"我也可以做到，而且做得更好。",
      synopsis:"羡慕是一个敏锐且善于观察的情绪，总是与他人做比较，渴望拥有别人所拥有的东西，被获取或超越的欲望所驱动。",
      traits:["不断把自己与他人的成就进行比较","对别人拥有或完成的事情有敏锐的洞察力","一种安静的决心，要获得或超越所钦佩的东西"],
      compatible:["厌恶","愤怒"] },
  };

  // ——— SBTI 人格扩展测试 ———
  const SBTI_DIMENSIONS = {
    S1: { name: "S1 自尊自信" }, S2: { name: "S2 自我清晰度" }, S3: { name: "S3 核心价值" },
    E1: { name: "E1 依恋安全感" }, E2: { name: "E2 情感投入度" }, E3: { name: "E3 边界与依赖" },
    A1: { name: "A1 世界观倾向" }, A2: { name: "A2 规则与灵活度" }, A3: { name: "A3 人生意义感" },
    Ac1: { name: "Ac1 动机导向" }, Ac2: { name: "Ac2 决策风格" }, Ac3: { name: "Ac3 执行模式" },
    So1: { name: "So1 社交主动性" }, So2: { name: "So2 人际边界感" }, So3: { name: "So3 表达与真实度" },
  };

  const SBTI_QUESTIONS = [
    { id: "q1", dim: "S1", text: "我不够好，周围的人都比我优秀", options: ["确实", "有时", "不是"] },
    { id: "q2", dim: "S1", text: "我会因为别人的优秀而明显怀疑自己", options: ["经常", "偶尔", "基本不会"] },
    { id: "q3", dim: "S2", text: "我很清楚真正的自己是什么样的", options: ["不认同", "中立", "认同"] },
    { id: "q4", dim: "S2", text: "我内心有真正追求的东西", options: ["不认同", "中立", "认同"] },
    { id: "q5", dim: "S3", text: "我一定要不断往上爬、变得更厉害", options: ["不认同", "中立", "认同"] },
    { id: "q6", dim: "S3", text: "外人的评价对我来说无所谓", options: ["不认同", "中立", "认同"] },
    { id: "q7", dim: "E1", text: "对象超过 5 小时没回消息时，你会怎么想？", options: ["更容易怀疑", "在怀疑和信任之间摇摆", "倾向先信任"] },
    { id: "q8", dim: "E1", text: "我在感情里经常担心被对方抛弃", options: ["是的", "偶尔", "不是"] },
    { id: "q9", dim: "E2", text: "我对待每一份感情都是认真的", options: ["并没有", "也许", "是的"] },
    { id: "q10", dim: "E2", text: "遇到很优秀且契合的对象，你会？", options: ["保持克制", "介于两者之间", "会非常投入"] },
    { id: "q11", dim: "E3", text: "恋爱后对象非常黏人时，你更接近？", options: ["那很爽", "都行", "更想保留独立空间"] },
    { id: "q12", dim: "E3", text: "我在关系里很重视个人空间", options: ["不太认同", "看情况", "非常认同"] },
    { id: "q13", dim: "A1", text: "大多数人是善良的", options: ["不太认同", "也许吧", "认同"] },
    { id: "q14", dim: "A1", text: "陌生人突然示好时，你更接近？", options: ["先警惕", "先观察", "先接纳"] },
    { id: "q15", dim: "A2", text: "规则和自由冲突时，你通常？", options: ["优先自由", "看场景", "优先规则"] },
    { id: "q16", dim: "A2", text: "我喜欢打破常规，不喜欢被束缚", options: ["认同", "中立", "不认同"] },
    { id: "q17", dim: "A3", text: "我做事通常有目标", options: ["不认同", "中立", "认同"] },
    { id: "q18", dim: "A3", text: "我会觉得很多事情没有真正意义", options: ["认同", "不确定", "不认同"] },
    { id: "q19", dim: "Ac1", text: "我做事更为取得成果，而不是只为避免风险", options: ["不认同", "中立", "认同"] },
    { id: "q20", dim: "Ac1", text: "面对卡住的任务，你更像？", options: ["先拖一拖", "再观察一下", "尽快想办法推进"] },
    { id: "q21", dim: "Ac2", text: "我做决定比较果断，不喜欢犹豫", options: ["不认同", "中立", "认同"] },
    { id: "q22", dim: "Ac2", text: "在信息不完整时，我通常？", options: ["继续犹豫", "边想边定", "先定再迭代"] },
    { id: "q23", dim: "Ac3", text: "别人说你执行力强，你更接近哪句？", options: ["被逼到最后才强", "有时", "事情就该被推进"] },
    { id: "q24", dim: "Ac3", text: "我做事常常有计划", options: ["计划常被打断", "有时能完成", "很讨厌被打乱"] },
    { id: "q25", dim: "So1", text: "在陌生社交场景中，你更接近？", options: ["慢热", "有人聊就聊", "主动打开场子"] },
    { id: "q26", dim: "So1", text: "朋友带了新朋友来，你通常？", options: ["天然有距离", "看情况", "会主动热情聊"] },
    { id: "q27", dim: "So2", text: "我和人相处有明显边界感", options: ["认同", "中立", "不认同"] },
    { id: "q28", dim: "So2", text: "我渴望和信任的人关系很亲密", options: ["认同", "中立", "不认同"] },
    { id: "q29", dim: "So3", text: "很多时候我会把真实负面看法收起来", options: ["较少", "看关系", "较多"] },
    { id: "q30", dim: "So3", text: "我在不同人面前会表现出不同的自己", options: ["不认同", "中立", "认同"] },
  ];

  const SBTI_SPECIAL_QUESTIONS = [
    { id: "drink_gate_q1", special: true, text: "您平时有什么爱好？", options: ["吃喝拉撒", "艺术爱好", "饮酒", "健身"] },
    { id: "drink_gate_q2", special: true, text: "您对饮酒的态度是？", options: ["小酌怡情", "习惯大量饮酒"] },
  ];

  const SBTI_TYPE_PATTERNS = [
    { code: "CTRL", pattern: "HHH-HMH-MHH-HHH-MHM" }, { code: "ATM-er", pattern: "HHH-HHM-HHH-HMH-MHL" },
    { code: "Dior-s", pattern: "MHM-MMH-MHM-HMH-LHL" }, { code: "BOSS", pattern: "HHH-HMH-MMH-HHH-LHL" },
    { code: "THAN-K", pattern: "MHM-HMM-HHM-MMH-MHL" }, { code: "OH-NO", pattern: "HHL-LMH-LHH-HHM-LHL" },
    { code: "GOGO", pattern: "HHM-HMH-MMH-HHH-MHM" }, { code: "SEXY", pattern: "HMH-HHL-HMM-HMM-HLH" },
    { code: "LOVE-R", pattern: "MLH-LHL-HLH-MLM-MLH" }, { code: "MUM", pattern: "MMH-MHL-HMM-LMM-HLL" },
    { code: "FAKE", pattern: "HLM-MML-MLM-MLM-HLH" }, { code: "OJBK", pattern: "MMH-MMM-HML-LMM-MML" },
    { code: "MALO", pattern: "MLH-MHM-MLH-MLH-LMH" }, { code: "JOKE-R", pattern: "LLH-LHL-LML-LLL-MLM" },
    { code: "WOC!", pattern: "HHL-HMH-MMH-HHM-LHH" }, { code: "THIN-K", pattern: "HHL-HMH-MLH-MHM-LHH" },
    { code: "SHIT", pattern: "HHL-HLH-LMM-HHM-LHH" }, { code: "ZZZZ", pattern: "MHL-MLH-LML-MML-LHM" },
    { code: "POOR", pattern: "HHL-MLH-LMH-HHH-LHL" }, { code: "MONK", pattern: "HHL-LLH-LLM-MML-LHM" },
    { code: "IMSB", pattern: "LLM-LMM-LLL-LLL-MLM" }, { code: "SOLO", pattern: "LML-LLH-LHL-LML-LHM" },
    { code: "FUCK", pattern: "MLL-LHL-LLM-MLL-HLH" }, { code: "DEAD", pattern: "LLL-LLM-LML-LLL-LHM" },
    { code: "IMFW", pattern: "LLH-LHL-LML-LLL-MLL" },
  ];

  const SBTI_TYPE_NAMES = {
    "CTRL": "拿捏者", "ATM-er": "送钱者", "Dior-s": "雕丝", "BOSS": "领导者", "THAN-K": "感恩者",
    "OH-NO": "哦不人", "GOGO": "行人", "SEXY": "尤物", "LOVE-R": "多情者", "MUM": "妈妈",
    "FAKE": "伪人", "OJBK": "无所谓人", "MALO": "吗喽", "JOKE-R": "小丑", "WOC!": "握草人",
    "THIN-K": "思考者", "SHIT": "愤世者", "ZZZZ": "装死者", "POOR": "贫困者", "MONK": "僧人",
    "IMSB": "傻者", "SOLO": "孤儿", "FUCK": "草者", "DEAD": "死者", "IMFW": "废物",
    "HHHH": "傻乐者", "DRUNK": "酒鬼",
  };

  const SBTI_DIMENSION_ORDER = ["S1", "S2", "S3", "E1", "E2", "E3", "A1", "A2", "A3", "Ac1", "Ac2", "Ac3", "So1", "So2", "So3"];

  const SBTI_DIMENSION_FEEDBACK = {
    S1: { L: "自我评价偏苛刻，容易先否定自己。", M: "自信会波动，受情境影响较大。", H: "自我评价更稳定，不易被外界扰动。" },
    S2: { L: "内在方向感较弱，容易迷茫。", M: "有方向，但会阶段性摇摆。", H: "对自己的目标与边界较清晰。" },
    S3: { L: "更偏稳态与舒适。", M: "成长与稳定并重。", H: "有较强进取与突破驱动力。" },
    E1: { L: "关系中的不安感偏高。", M: "信任与怀疑并存。", H: "关系安全感较强。" },
    E2: { L: "投入偏谨慎保守。", M: "投入与自保并行。", H: "投入深度较高。" },
    E3: { L: "更偏亲密黏性。", M: "亲密与空间可调。", H: "个人边界与独立感更强。" },
    A1: { L: "更偏防御性视角。", M: "保持观察，不轻易下结论。", H: "更倾向相信善意与合作。" },
    A2: { L: "灵活与自由优先。", M: "规则与变通平衡。", H: "秩序与流程优先。" },
    A3: { L: "意义感较弱，容易空转。", M: "意义感阶段性起伏。", H: "方向感与意义感较稳定。" },
    Ac1: { L: "以避险为主。", M: "推进与避险并重。", H: "以成果导向与推进为主。" },
    Ac2: { L: "决策偏慢，犹豫较多。", M: "决策速度适中。", H: "决策果断度较高。" },
    Ac3: { L: "执行常依赖截止压力。", M: "执行稳定性中等。", H: "执行推进感更强。" },
    So1: { L: "社交启动慢热。", M: "社交弹性中等。", H: "更愿意主动社交。" },
    So2: { L: "更偏关系融合。", M: "边界感可调。", H: "边界意识较强。" },
    So3: { L: "表达更直接。", M: "表达会考虑场景。", H: "擅长分层表达真实想法。" },
  };

  const SBTI_ALWAYS_INCLUDED_SPECIAL_QUESTION = SBTI_SPECIAL_QUESTIONS[0];
  const SBTI_CONDITIONAL_SPECIAL_QUESTION = SBTI_SPECIAL_QUESTIONS[1];
  const SBTI_HIDDEN_RESULT_TRIGGER_ID = "drink_gate_q2";

  /* ====================================================
   * 二、状态与存储
   * ==================================================== */

  const HISTORY_KEY_PREFIX = "dp_deeptest_hist_v2_";
  const RESULT_KEY_PREFIX = "dp_deeptest_result_v1_";
  const SBTI_PROFILE_KEY = "sbti_profile";
  const SBTI_LEGACY_PROFILE_KEY = "sbti_profile_v1";
  const HISTORY_LIMIT = 12;

  const st = {
    modal: null,   // 'friends' | 'insideout' | 'deep' | 'sbti'
    friends:  { idx: 0, ans: {}, result: null },
    insideout:{ idx: 0, ans: {}, result: null },
    deep:     { idx: 0, ans: {}, result: null, aiText: null, aiLoading: false },
    sbti:     { idx: 0, ans: {}, result: null },
    store:    { friends: null, insideout: null, deep: null, sbti: null },
    hist:     { runs: [], prev: null, cur: null },
  };

  function resolveCurrentUsername() {
    let u = "guest";
    try {
      if (typeof window.getCurrentUser === "function") {
        const usr = window.getCurrentUser();
        if (usr && usr.username) u = usr.username;
      }
    } catch(_) {}
    return u;
  }

  function storageKey() {
    return HISTORY_KEY_PREFIX + resolveCurrentUsername();
  }

  function resultStorageKey() {
    return RESULT_KEY_PREFIX + resolveCurrentUsername();
  }

  function getSbtiProfile() {
    try {
      const currentRaw = localStorage.getItem(SBTI_PROFILE_KEY);
      if (currentRaw) {
        const currentParsed = JSON.parse(currentRaw);
        if (currentParsed && typeof currentParsed === "object") return currentParsed;
      }
    } catch (_) {}
    try {
      const legacyRaw = localStorage.getItem(SBTI_LEGACY_PROFILE_KEY);
      if (!legacyRaw) return null;
      const legacyParsed = JSON.parse(legacyRaw);
      if (!legacyParsed || typeof legacyParsed !== "object") return null;
      try {
        localStorage.setItem(SBTI_PROFILE_KEY, JSON.stringify(legacyParsed));
        localStorage.removeItem(SBTI_LEGACY_PROFILE_KEY);
      } catch (_) {}
      return legacyParsed;
    } catch (_) {
      return null;
    }
  }

  function normalizeDeepResult(raw) {
    if (!raw || typeof raw !== "object") return null;
    const type = String(raw.type || "").trim().toUpperCase();
    if (!type) return null;
    const axisScores = {
      IE: Number(raw.axisScores?.IE || 0),
      SN: Number(raw.axisScores?.SN || 0),
      TF: Number(raw.axisScores?.TF || 0),
      JP: Number(raw.axisScores?.JP || 0),
    };
    return {
      completed: true,
      answeredCount: Number(raw.answeredCount || DEEP_Q.length),
      type,
      axisScores,
      pct: {
        IE: Number(raw.pct?.IE || 0),
        SN: Number(raw.pct?.SN || 0),
        TF: Number(raw.pct?.TF || 0),
        JP: Number(raw.pct?.JP || 0),
      },
    };
  }

  function normalizeGameResult(raw, pool) {
    if (!raw || typeof raw !== "object") return null;
    const winner = String(raw.winner || "").trim();
    if (!winner || !pool[winner]) return null;
    const detailRaw = raw.detail && typeof raw.detail === "object" ? raw.detail : pool[winner];
    const scoreRaw = raw.scores && typeof raw.scores === "object" ? raw.scores : {};
    const scores = {};
    Object.keys(pool).forEach((key) => {
      scores[key] = Number(scoreRaw[key] || 0);
    });
    return {
      winner,
      scores,
      completedAt: Number(raw.completedAt || Date.now()),
      detail: {
        name: String(detailRaw.name || pool[winner].name || winner),
        emoji: String(detailRaw.emoji || pool[winner].emoji || ""),
        color: String(detailRaw.color || pool[winner].color || "#6366f1"),
        tagline: String(detailRaw.tagline || ""),
        synopsis: String(detailRaw.synopsis || ""),
        traits: Array.isArray(detailRaw.traits)
          ? detailRaw.traits.map(v => String(v || "").trim()).filter(Boolean).slice(0, 8)
          : [],
        compatible: Array.isArray(detailRaw.compatible)
          ? detailRaw.compatible.map(v => String(v || "").trim()).filter(Boolean).slice(0, 8)
          : [],
      },
    };
  }

  function normalizeSbtiResult(raw) {
    if (!raw || typeof raw !== "object") return null;
    const rawCode = String(raw.code || "").trim();
    const code = rawCode === "OG8K" ? "OJBK" : rawCode;
    if (!code) return null;
    const levels = raw.levels && typeof raw.levels === "object" ? raw.levels : {};
    const rawScores = raw.rawScores && typeof raw.rawScores === "object" ? raw.rawScores : {};
    const normalizedLevels = {};
    const normalizedRawScores = {};
    SBTI_DIMENSION_ORDER.forEach((key) => {
      const level = String(levels[key] || "").trim().toUpperCase();
      normalizedLevels[key] = ["L", "M", "H"].includes(level) ? level : "M";
      normalizedRawScores[key] = Number(rawScores[key] || 0);
    });
    return {
      code,
      title: String(raw.title || `${code}（${SBTI_TYPE_NAMES[code] || code}）`),
      match: Number(raw.match || 0),
      badge: String(raw.badge || ""),
      mode: String(raw.mode || "你的主类型"),
      summary: String(raw.summary || "已生成人格扩展画像。"),
      levels: normalizedLevels,
      rawScores: normalizedRawScores,
      completedAt: Number(raw.completedAt || Date.now()),
    };
  }

  function normalizeHistEntry(raw) {
    if (!raw || typeof raw !== "object") return null;
    const type = String(raw.type || "").trim().toUpperCase();
    if (!type) return null;
    const axisScores = { IE: 0, SN: 0, TF: 0, JP: 0 };
    ["IE", "SN", "TF", "JP"].forEach((axis) => {
      axisScores[axis] = Number(raw.axisScores?.[axis] || 0);
    });
    return {
      type,
      axisScores,
      pct: {
        IE: Number(raw.pct?.IE || 0),
        SN: Number(raw.pct?.SN || 0),
        TF: Number(raw.pct?.TF || 0),
        JP: Number(raw.pct?.JP || 0),
      },
      answeredCount: Number(raw.answeredCount || DEEP_Q.length),
      savedAt: Number(raw.savedAt || Date.now()),
    };
  }

  function syncHistPair() {
    const runs = Array.isArray(st.hist.runs) ? [...st.hist.runs] : [];
    runs.sort((a, b) => Number(a.savedAt || 0) - Number(b.savedAt || 0));
    st.hist.runs = runs.slice(-HISTORY_LIMIT);
    st.hist.cur = st.hist.runs.at(-1) || null;
    st.hist.prev = st.hist.runs.length >= 2 ? st.hist.runs.at(-2) : null;
  }

  function buildDeepResultFromHist(entry) {
    if (!entry) return null;
    const pct = entry.pct || {};
    return {
      completed: true,
      answeredCount: Number(entry.answeredCount || DEEP_Q.length),
      type: entry.type,
      axisScores: { ...entry.axisScores },
      pct: {
        IE: Number(pct.IE || 0),
        SN: Number(pct.SN || 0),
        TF: Number(pct.TF || 0),
        JP: Number(pct.JP || 0),
      },
    };
  }

  function persistStoredResults() {
    try {
      localStorage.setItem(resultStorageKey(), JSON.stringify(st.store));
    } catch(_) {}
  }

  function saveFriendsStore(result, completedAt) {
    if (!result || !result.winner || !FRIENDS_RESULTS[result.winner]) return;
    const detail = FRIENDS_RESULTS[result.winner];
    st.store.friends = {
      winner: result.winner,
      scores: { ...(result.scores || {}) },
      completedAt: Number(completedAt || Date.now()),
      detail: {
        name: detail.name,
        emoji: detail.emoji,
        color: detail.color,
        tagline: detail.tagline,
        synopsis: detail.synopsis,
        traits: [...detail.traits],
        compatible: [...detail.compatible],
      },
    };
    persistStoredResults();
  }

  function saveInsideOutStore(result, completedAt) {
    if (!result || !result.winner || !IO_RESULTS[result.winner]) return;
    const detail = IO_RESULTS[result.winner];
    st.store.insideout = {
      winner: result.winner,
      scores: { ...(result.scores || {}) },
      completedAt: Number(completedAt || Date.now()),
      detail: {
        name: detail.name,
        emoji: detail.emoji,
        color: detail.color,
        tagline: detail.tagline,
        synopsis: detail.synopsis,
        traits: [...detail.traits],
        compatible: [...detail.compatible],
      },
    };
    persistStoredResults();
  }

  function saveDeepStore(result, completedAt) {
    const normalized = normalizeDeepResult(result);
    if (!normalized) return;
    st.store.deep = {
      result: normalized,
      completedAt: Number(completedAt || Date.now()),
      aiText: st.deep.aiText ? String(st.deep.aiText) : "",
    };
    persistStoredResults();
  }

  function saveSbtiStore(result, completedAt) {
    const normalized = normalizeSbtiResult(result);
    if (!normalized) return;
    st.store.sbti = normalized;
    st.sbti.result = { ...normalized };
    try {
      localStorage.setItem(SBTI_PROFILE_KEY, JSON.stringify(normalized));
      localStorage.removeItem(SBTI_LEGACY_PROFILE_KEY);
    } catch (_) {}
    persistStoredResults();
  }

  function loadStoredResults() {
    st.store = { friends: null, insideout: null, deep: null, sbti: null };
    try {
      const raw = localStorage.getItem(resultStorageKey());
      if (raw) {
        const data = JSON.parse(raw);
        st.store.friends = normalizeGameResult(data?.friends, FRIENDS_RESULTS);
        st.store.insideout = normalizeGameResult(data?.insideout, IO_RESULTS);
        const deepResult = normalizeDeepResult(data?.deep?.result);
        st.store.deep = deepResult
          ? {
              result: deepResult,
              completedAt: Number(data?.deep?.completedAt || Date.now()),
              aiText: String(data?.deep?.aiText || ""),
            }
          : null;
        st.store.sbti = normalizeSbtiResult(data?.sbti);
      }
    } catch(_) {
      st.store = { friends: null, insideout: null, deep: null, sbti: null };
    }

    if (!st.store.sbti) {
      const legacySbti = normalizeSbtiResult(getSbtiProfile());
      if (legacySbti) {
        st.store.sbti = legacySbti;
        persistStoredResults();
      }
    }

    if (st.store.friends) {
      st.friends.result = {
        winner: st.store.friends.winner,
        scores: { ...st.store.friends.scores },
      };
    }
    if (st.store.insideout) {
      st.insideout.result = {
        winner: st.store.insideout.winner,
        scores: { ...st.store.insideout.scores },
      };
    }
    if (st.store.deep?.result) {
      st.deep.result = { ...st.store.deep.result };
    }
    if (st.store.deep?.aiText) {
      st.deep.aiText = String(st.store.deep.aiText || "");
    }
    if (st.store.sbti) {
      st.sbti.result = { ...st.store.sbti };
    }
  }

  function loadHist() {
    try {
      const raw = localStorage.getItem(storageKey());
      st.hist = { runs: [], prev: null, cur: null };
      if (!raw) return;
      const data = JSON.parse(raw);
      if (data && Array.isArray(data.runs)) {
        st.hist.runs = data.runs.map(normalizeHistEntry).filter(Boolean);
      } else if (data && typeof data === "object") {
        const legacyRuns = [normalizeHistEntry(data.prev), normalizeHistEntry(data.cur)].filter(Boolean);
        st.hist.runs = legacyRuns;
      } else if (Array.isArray(data)) {
        st.hist.runs = data.map(normalizeHistEntry).filter(Boolean);
      }
      syncHistPair();
      if (st.hist.cur) {
        st.deep.result = buildDeepResultFromHist(st.hist.cur);
      }
    } catch(_) {}
  }

  /* ====================================================
   * 三、计算
   * ==================================================== */

  function computeDeep() {
    const s = { IE:0, SN:0, TF:0, JP:0 };
    let cnt = 0;
    DEEP_Q.forEach(q => {
      const v = st.deep.ans[q.id];
      if (v === undefined) return;
      cnt++;
      s[q.axis] += q.dir * v;
    });
    const E = s.IE >= 0, N = s.SN >= 0, F = s.TF >= 0, P = s.JP >= 0;
    const type = (E?"E":"I") + (N?"N":"S") + (F?"F":"T") + (P?"P":"J");
    // 各轴题数用于百分比
    const cnt_ = ax => DEEP_Q.filter(q => q.axis === ax).length;
    const pct  = ax => Math.min(100, Math.round(Math.abs(s[ax]) / (cnt_(ax) * 2) * 100));
    return {
      completed: cnt >= DEEP_Q.length,
      answeredCount: cnt,
      type, axisScores: {...s},
      pct: { IE: pct("IE"), SN: pct("SN"), TF: pct("TF"), JP: pct("JP") },
    };
  }

  function computeFriends() {
    const scores = { Ross:0, Joey:0, Phoebe:0, Monica:0, Chandler:0, Rachel:0 };
    Object.entries(st.friends.ans).forEach(([qId, v]) => {
      const m = FRIENDS_SCORE[+qId];
      if (m && m[v]) m[v].forEach(ch => { scores[ch] = (scores[ch]||0) + 1; });
    });
    const winner = Object.entries(scores).sort((a,b)=>b[1]-a[1])[0];
    return { winner: winner ? winner[0] : null, scores };
  }

  function computeIO() {
    const scores = {};
    Object.keys(IO_RESULTS).forEach(k => { scores[k] = 0; });
    Object.values(st.insideout.ans).forEach(emo => { scores[emo] = (scores[emo]||0) + 1; });
    const winner = Object.entries(scores).sort((a,b)=>b[1]-a[1])[0];
    return { winner: winner ? winner[0] : null, scores };
  }

  function computeFriendsFromAnswers(answers) {
    const prevAns = st.friends.ans;
    st.friends.ans = { ...(answers || {}) };
    const result = computeFriends();
    st.friends.ans = prevAns;
    return result;
  }

  function computeIOFromAnswers(answers) {
    const prevAns = st.insideout.ans;
    st.insideout.ans = { ...(answers || {}) };
    const result = computeIO();
    st.insideout.ans = prevAns;
    return result;
  }

  function computeDeepFromAnswers(answers) {
    const nextAnswers = {};
    Object.entries(answers || {}).forEach(([k, v]) => {
      const qId = Number(k);
      const score = Number(v);
      if (!Number.isFinite(qId) || !Number.isFinite(score)) return;
      nextAnswers[qId] = score;
    });
    const prevAns = st.deep.ans;
    st.deep.ans = nextAnswers;
    const result = computeDeep();
    st.deep.ans = prevAns;
    return result;
  }

  function shuffleSbtiQuestions(items) {
    const cloned = Array.isArray(items) ? [...items] : [];
    for (let i = cloned.length - 1; i > 0; i -= 1) {
      const ri = Math.floor(Math.random() * (i + 1));
      [cloned[i], cloned[ri]] = [cloned[ri], cloned[i]];
    }
    return cloned;
  }

  function getSbtiQuestionSet() {
    const stored = Array.isArray(st.sbti.order) && st.sbti.order.length ? st.sbti.order : [];
    const base = stored.length
      ? stored.map((id) => SBTI_QUESTIONS.find((item) => item.id === id)).filter(Boolean)
      : SBTI_QUESTIONS;
    const list = [...base];
    const insertIndex = list.findIndex((item) => item.id === SBTI_ALWAYS_INCLUDED_SPECIAL_QUESTION.id);
    if (insertIndex === -1) {
      const fallbackInsertAt = Math.min(list.length, Math.max(1, Number(st.sbti.insertAt || 1)));
      list.splice(fallbackInsertAt, 0, SBTI_ALWAYS_INCLUDED_SPECIAL_QUESTION);
    }
    const specialIndex = list.findIndex((item) => item.id === SBTI_ALWAYS_INCLUDED_SPECIAL_QUESTION.id);
    if (specialIndex !== -1 && Number(st.sbti.ans[SBTI_ALWAYS_INCLUDED_SPECIAL_QUESTION.id]) === 3) {
      list.splice(specialIndex + 1, 0, SBTI_CONDITIONAL_SPECIAL_QUESTION);
    }
    return list;
  }

  function computeSbtiFromAnswers(answers) {
    const nextAnswers = {};
    Object.entries(answers || {}).forEach(([k, v]) => {
      const key = String(k || "").trim();
      const score = Number(v);
      if (!key || !Number.isFinite(score)) return;
      nextAnswers[key] = score;
    });

    const rawScores = Object.fromEntries(Object.keys(SBTI_DIMENSIONS).map((key) => [key, 0]));
    SBTI_QUESTIONS.forEach((q) => {
      rawScores[q.dim] += Number(nextAnswers[q.id] || 0);
    });

    const scoreToLevel = (score) => {
      if (score <= 3) return "L";
      if (score === 4) return "M";
      return "H";
    };
    const levelToWeight = (level) => ({ L: 1, M: 2, H: 3 }[level] || 1);
    const splitPattern = (pattern) => String(pattern || "").replace(/-/g, "").split("");

    const levels = Object.fromEntries(Object.entries(rawScores).map(([key, value]) => [key, scoreToLevel(value)]));
    const userPattern = SBTI_DIMENSION_ORDER.map((key) => levelToWeight(levels[key]));

    const ranked = SBTI_TYPE_PATTERNS.map((tp) => {
      const pattern = splitPattern(tp.pattern).map(levelToWeight);
      let distance = 0;
      let exact = 0;
      pattern.forEach((weight, idx) => {
        const delta = Math.abs(userPattern[idx] - weight);
        distance += delta;
        if (delta === 0) exact += 1;
      });
      return {
        code: tp.code,
        distance,
        exact,
        similarity: Math.max(0, Math.round((1 - distance / 30) * 100)),
      };
    }).sort((a, b) => (a.distance - b.distance) || (b.exact - a.exact) || (b.similarity - a.similarity));

    const best = ranked[0] || { code: "HHHH", similarity: 0, exact: 0 };
    let finalCode = best.code;
    let mode = "你的主类型";
    let summary = "维度命中度较高，当前结果可视为你的第一人格画像。";

    if (Number(nextAnswers[SBTI_HIDDEN_RESULT_TRIGGER_ID]) === 2) {
      finalCode = "DRUNK";
      mode = "隐藏人格已激活";
      summary = "饮酒补充题触发隐藏人格分支。";
    } else if (best.similarity < 60) {
      finalCode = "HHHH";
      mode = "系统强制兜底";
      summary = "标准人格库最高匹配较低，已落入兜底人格。";
    }

    const finalName = SBTI_TYPE_NAMES[finalCode] || finalCode;
    return {
      code: finalCode,
      title: `${finalCode}（${finalName}）`,
      match: finalCode === "DRUNK" ? 100 : Number(best.similarity || 0),
      badge: finalCode === "DRUNK"
        ? "匹配度 100% · 隐藏分支"
        : `匹配度 ${Number(best.similarity || 0)}% · 命中 ${Number(best.exact || 0)}/15`,
      mode,
      summary,
      levels,
      rawScores,
      completedAt: Date.now(),
    };
  }

  /* ====================================================
   * 四、工具函数
   * ==================================================== */

  function esc(v) {
    return String(v||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }

  function $id(id) { return document.getElementById(id); }

  function notify(title, text, type) {
    if (typeof window.showToast === "function") window.showToast(title, text||"", type||"info", 2200);
  }

  function sanitizeTestType(raw) {
    const v = String(raw || "").trim().toLowerCase();
    return ["friends", "insideout", "deep", "sbti"].includes(v) ? v : "deep";
  }

  function resultPageUrl(type) {
    const safeType = sanitizeTestType(type);
    return `/test-result.html?test=${encodeURIComponent(safeType)}`;
  }

  function runnerPageUrl(type, restart) {
    const safeType = sanitizeTestType(type);
    const suffix = restart ? "&restart=1" : "";
    return `/test-runner.html?test=${encodeURIComponent(safeType)}${suffix}`;
  }

  window.openDeepTestRunnerPage = function(type, restart) {
    const safeType = sanitizeTestType(type);
    closeDeepTestModal();
    window.location.href = runnerPageUrl(safeType, Boolean(restart));
  };

  window.openDeepTestResultPage = function(type) {
    const safeType = sanitizeTestType(type);
    closeDeepTestModal();
    window.location.href = resultPageUrl(safeType);
  };

  window.openSBTITestPage = function() {
    closeDeepTestModal();
    window.location.href = runnerPageUrl("sbti", true);
  };

  window.openSBTIResultPage = function() {
    closeDeepTestModal();
    window.location.href = resultPageUrl("sbti");
  };

  /* ====================================================
   * 五、模态框骨架
   * ==================================================== */

  function openDeepTestModal(type) {
    st.modal = sanitizeTestType(type);
    const modal = $id("deepTestModal");
    if (modal) { modal.classList.remove("hidden"); document.body.style.overflow = "hidden"; }
    renderModal();
  }

  function closeDeepTestModal() {
    const modal = $id("deepTestModal");
    if (modal) { modal.classList.add("hidden"); document.body.style.overflow = ""; }
    st.modal = null;
    refreshCards();
  }

  function renderModal() {
    if (!st.modal) return;
    if (st.modal === "friends")   renderFriendsModal();
    if (st.modal === "insideout") renderIOModal();
    if (st.modal === "deep")      renderDeepModal();
  }

  window.openDeepTestModal = openDeepTestModal;
  window.closeDeepTestModal = closeDeepTestModal;
  window.handleDeepTestOverlayClick = function(e) {
    if (e.target && e.target.id === "deepTestModal") closeDeepTestModal();
  };

  function setModalShell(title, subtitle, curQ, totalQ) {
    const hEl = $id("dtModalTitle");
    const sEl = $id("dtModalSub");
    const pEl = $id("dtModalProgress");
    const bEl = $id("dtModalProgressBar");
    if (hEl) hEl.textContent = title;
    if (sEl) sEl.textContent = subtitle;
    const pct = totalQ ? Math.round(curQ / totalQ * 100) : 0;
    if (pEl) pEl.textContent = `${curQ} / ${totalQ}`;
    if (bEl) bEl.style.width = pct + "%";
  }

  /* ====================================================
   * 六、老友记游戏
   * ==================================================== */

  function renderFriendsModal() {
    const total   = FRIENDS_Q.length;
    const answered = Object.keys(st.friends.ans).length;

    if (answered >= total) {
      let r = st.friends.result;
      if (!r || !r.winner) {
        r = computeFriends();
        st.friends.result = r;
        const completedAt = Date.now();
        saveFriendsStore(r, completedAt);
        refreshCards();
      }
      if (!st.store.friends?.winner) {
        saveFriendsStore(r, Date.now());
      }
      openDeepTestResultPage("friends");
      return;
    }

    const q = FRIENDS_Q[st.friends.idx];
    setModalShell("🎬 你是哪个老友记角色？", `第 ${st.friends.idx+1} 题，共 ${total} 题`, answered, total);
    const sel = st.friends.ans[q.id];
    $id("dtModalContent").innerHTML = `
      <div class="dt-q-card">
        <div class="dt-q-num">第 ${st.friends.idx+1} / ${total} 题</div>
        <h3 class="dt-q-text">${esc(q.text)}</h3>
        <div class="dt-opts-grid">
          ${q.opts.map(o=>`
            <button class="dt-opt ${sel===o.v?"selected":""}" onclick="submitFriendsAns(${q.id},'${o.v}')">${esc(o.t)}</button>
          `).join("")}
        </div>
        <div class="dt-q-nav">
          <button class="dt-nav-btn" onclick="friendsPrev()" ${st.friends.idx<=0?"disabled":""}>← 上一题</button>
          <button class="dt-nav-btn primary" onclick="friendsNext()" ${sel===undefined?"disabled":""}>
            ${st.friends.idx>=total-1?"查看结果 →":"下一题 →"}
          </button>
        </div>
      </div>`;
  }

  window.submitFriendsAns = function(qId, v) {
    st.friends.ans[qId] = v;
    const idx = FRIENDS_Q.findIndex(q=>q.id===qId);
    if (idx>=0) st.friends.idx = Math.min(idx+1, FRIENDS_Q.length-1);
    renderFriendsModal();
  };
  window.friendsPrev = function() { st.friends.idx = Math.max(0, st.friends.idx-1); renderFriendsModal(); };
  window.friendsNext = function() {
    const q = FRIENDS_Q[st.friends.idx];
    if (st.friends.ans[q.id]===undefined) return;
    st.friends.idx = Math.min(st.friends.idx+1, FRIENDS_Q.length-1);
    renderFriendsModal();
  };
  window.restartFriends = function() { st.friends = {idx:0, ans:{}, result:null}; renderFriendsModal(); };

  /* ====================================================
   * 七、头脑特工队游戏
   * ==================================================== */

  function renderIOModal() {
    const total   = IO_Q.length;
    const answered = Object.keys(st.insideout.ans).length;

    if (answered >= total) {
      let r = st.insideout.result;
      if (!r || !r.winner) {
        r = computeIO();
        st.insideout.result = r;
        const completedAt = Date.now();
        saveInsideOutStore(r, completedAt);
        refreshCards();
      }
      if (!st.store.insideout?.winner) {
        saveInsideOutStore(r, Date.now());
      }
      openDeepTestResultPage("insideout");
      return;
    }

    const q = IO_Q[st.insideout.idx];
    setModalShell("🎭 你是哪种情绪？", `第 ${st.insideout.idx+1} 题，共 ${total} 题`, answered, total);
    const sel = st.insideout.ans[q.id];
    $id("dtModalContent").innerHTML = `
      <div class="dt-q-card">
        <div class="dt-q-num">第 ${st.insideout.idx+1} / ${total} 题</div>
        <h3 class="dt-q-text">${esc(q.text)}</h3>
        <div class="dt-opts-grid">
          ${q.opts.map(o=>`
            <button class="dt-opt ${sel===o.v?"selected":""}" onclick="submitIOAns(${q.id},'${esc(o.v)}')">${esc(o.t)}</button>
          `).join("")}
        </div>
        <div class="dt-q-nav">
          <button class="dt-nav-btn" onclick="ioPrev()" ${st.insideout.idx<=0?"disabled":""}>← 上一题</button>
          <button class="dt-nav-btn primary" onclick="ioNext()" ${sel===undefined?"disabled":""}>
            ${st.insideout.idx>=total-1?"查看结果 →":"下一题 →"}
          </button>
        </div>
      </div>`;
  }

  window.submitIOAns = function(qId, v) {
    st.insideout.ans[qId] = v;
    const idx = IO_Q.findIndex(q=>q.id===qId);
    if (idx>=0) st.insideout.idx = Math.min(idx+1, IO_Q.length-1);
    renderIOModal();
  };
  window.ioPrev = function() { st.insideout.idx = Math.max(0, st.insideout.idx-1); renderIOModal(); };
  window.ioNext = function() {
    const q = IO_Q[st.insideout.idx];
    if (st.insideout.ans[q.id]===undefined) return;
    st.insideout.idx = Math.min(st.insideout.idx+1, IO_Q.length-1);
    renderIOModal();
  };
  window.restartIO = function() { st.insideout = {idx:0, ans:{}, result:null}; renderIOModal(); };

  /* ====================================================
   * 八、通用结果卡片（游戏用）
   * ==================================================== */

  function renderGameResult(emoji, name, color, tagline, synopsis, traits, compatible, restartFn, testType) {
    return `
      <div class="dt-result-wrap">
        <div class="dt-result-hero" style="background:linear-gradient(135deg,${color}22,${color}55);">
          <div class="dt-r-emoji">${esc(emoji)}</div>
          <div class="dt-r-name">${esc(name)}</div>
          <div class="dt-r-tagline">"${esc(tagline)}"</div>
        </div>
        <p class="dt-r-synopsis">${esc(synopsis)}</p>
        <div class="dt-r-section">
          <p class="dt-r-label">你们共有的特质</p>
          <ul class="dt-r-traits">
            ${traits.map(t=>`<li>${esc(t)}</li>`).join("")}
          </ul>
        </div>
        <div class="dt-r-section">
          <p class="dt-r-label">与你最合拍的</p>
          <div class="dt-r-tags">
            ${compatible.map(c=>`<span class="dt-r-tag">${esc(c)}</span>`).join("")}
          </div>
        </div>
        <div class="dt-q-nav" style="margin-top:1.5rem">
          <button class="dt-nav-btn" onclick="openDeepTestResultPage('${esc(testType || "deep")}')">查看完整结果页</button>
          <button class="dt-nav-btn" onclick="${restartFn}">再测一次</button>
          <button class="dt-nav-btn primary" onclick="closeDeepTestModal()">返回</button>
        </div>
      </div>`;
  }

  /* ====================================================
   * 九、深层 MBTI 测试
   * ==================================================== */

  function renderDeepModal() {
    const total   = DEEP_Q.length;
    const answered = Object.keys(st.deep.ans).length;

    if (st.deep.result) {
      if (!st.store.deep?.result) {
        saveDeepStore(st.deep.result, Date.now());
      }
      openDeepTestResultPage("deep");
      return;
    }
    if (answered >= total) {
      const r = computeDeep();
      st.deep.result = r;
      const completedAt = Date.now();
      saveDeepStore(r, completedAt);
      refreshCards();
      openDeepTestResultPage("deep");
      return;
    }

    const q = DEEP_Q[st.deep.idx];
    setModalShell("🧬 深层性格探索", `第 ${st.deep.idx+1} 题，共 ${total} 题`, answered, total);
    const sel = st.deep.ans[q.id];
    $id("dtModalContent").innerHTML = `
      <div class="dt-q-card deep">
        <div class="dt-q-num">第 ${st.deep.idx+1} / ${total} 题</div>
        <h3 class="dt-q-text">${esc(q.text)}</h3>
        <div class="dt-likert-wrap">
          ${DEEP_ANSWERS.map(a=>`
            <button class="dt-likert-btn ${sel===a.value?"selected":""}" onclick="submitDeepAns(${q.id},${a.value})">
              ${esc(a.label)}
            </button>
          `).join("")}
        </div>
        <div class="dt-q-nav">
          <button class="dt-nav-btn" onclick="deepPrev()" ${st.deep.idx<=0?"disabled":""}>← 上一题</button>
          <button class="dt-nav-btn primary" onclick="deepNext()" ${sel===undefined?"disabled":""}>
            ${st.deep.idx>=total-1?"查看结果 →":"下一题 →"}
          </button>
        </div>
      </div>`;
  }

  function renderDeepResult(r) {
    const typeName  = MBTI_NAMES[r.type]  || r.type;
    const typeEmoji = MBTI_EMOJI[r.type]  || "🧩";
    const E = r.axisScores.IE >= 0, N = r.axisScores.SN >= 0;
    const F = r.axisScores.TF >= 0, P = r.axisScores.JP >= 0;

    const dims = [
      { pair:"IE", left:"外向 E", right:"内向 I", active: E, score: r.axisScores.IE, pct: r.pct.IE },
      { pair:"SN", left:"直觉 N", right:"感觉 S", active: N, score: r.axisScores.SN, pct: r.pct.SN },
      { pair:"TF", left:"情感 F", right:"思考 T", active: F, score: r.axisScores.TF, pct: r.pct.TF },
      { pair:"JP", left:"感知 P", right:"判断 J", active: P, score: r.axisScores.JP, pct: r.pct.JP },
    ];

    const dimHtml = dims.map(d => `
      <div class="dt-dim">
        <div class="dt-dim-head">
          <span class="dt-dim-tag ${d.active?"active":""}">${esc(d.active?d.left:d.right)}</span>
          <span class="dt-dim-score">${d.score>0?"+":""}${d.score}</span>
          <span class="dt-dim-tag ${!d.active?"active":""}">${esc(d.active?d.right:d.left)}</span>
        </div>
        <div class="dt-dim-track"><div class="dt-dim-fill" style="width:${d.pct}%"></div></div>
        <div class="dt-dim-pct">${d.pct}% 倾向 ${esc(d.active?d.left:d.right)}</div>
      </div>`).join("");

    const aiHtml = st.deep.aiText
      ? `<div class="dt-ai-box">
           <div class="dt-ai-box-head">✨ AI 深度分析</div>
           <div class="dt-ai-box-body">${esc(st.deep.aiText).replace(/\n/g,"<br>")}</div>
         </div>`
      : `<div class="dt-ai-placeholder">
           <button class="dt-ai-trigger ${st.deep.aiLoading?"dt-ai-loading":""}"
                   onclick="requestDeepAI()" ${st.deep.aiLoading?"disabled":""}>
             ${st.deep.aiLoading?"⏳ AI 分析生成中…":"✨ 获取 AI 深度分析"}
           </button>
           <p class="dt-ai-hint">AI 将根据你的具体作答情况，生成个性化的心理分析和成长建议。</p>
         </div>`;

    return `
      <div class="dt-result-wrap">
        <div class="dt-result-hero deep-hero">
          <div class="dt-r-emoji">${typeEmoji}</div>
          <div class="dt-r-name">${esc(r.type)}</div>
          <div class="dt-r-tagline">${esc(typeName)}</div>
        </div>
        <div class="dt-dims-wrap">
          <p class="dt-r-label">维度分析</p>
          ${dimHtml}
        </div>
        ${aiHtml}
        <div class="dt-q-nav" style="margin-top:1.5rem">
          <button class="dt-nav-btn" onclick="openDeepTestResultPage('deep')">查看完整结果页</button>
          <button class="dt-nav-btn" onclick="restartDeep()">重新测试</button>
          <button class="dt-nav-btn primary" onclick="closeDeepTestModal()">返回</button>
        </div>
      </div>`;
  }

  window.submitDeepAns = function(qId, v) {
    st.deep.ans[qId] = v;
    const idx = DEEP_Q.findIndex(q=>q.id===qId);
    if (idx>=0) st.deep.idx = Math.min(idx+1, DEEP_Q.length-1);
    renderDeepModal();
  };
  window.deepPrev = function() { st.deep.idx = Math.max(0, st.deep.idx-1); renderDeepModal(); };
  window.deepNext = function() {
    const q = DEEP_Q[st.deep.idx];
    if (st.deep.ans[q.id]===undefined) return;
    st.deep.idx = Math.min(st.deep.idx+1, DEEP_Q.length-1);
    renderDeepModal();
  };
  window.restartDeep = function() {
    st.deep = {idx:0, ans:{}, result:null, aiText:null, aiLoading:false};
    renderDeepModal();
  };

  window.requestDeepAI = async function() {
    if (st.deep.aiLoading || !st.deep.result) return;
    st.deep.aiLoading = true;
    renderDeepModal();
    try {
      const apiUrl = typeof window.resolveApiUrl === "function"
        ? window.resolveApiUrl("/api/deep-test-analysis")
        : "/api/deep-test-analysis";
      const r = st.deep.result;
      const dimDetails = [
        {axis:"IE", label: r.axisScores.IE>=0?"外向(E)":"内向(I)", score: r.axisScores.IE},
        {axis:"SN", label: r.axisScores.SN>=0?"直觉(N)":"感觉(S)", score: r.axisScores.SN},
        {axis:"TF", label: r.axisScores.TF>=0?"情感(F)":"思考(T)", score: r.axisScores.TF},
        {axis:"JP", label: r.axisScores.JP>=0?"感知(P)":"判断(J)", score: r.axisScores.JP},
      ];
      const resp = await fetch(apiUrl, {
        method:"POST", headers:{"Content-Type":"application/json"},
        credentials: "include",
        body: JSON.stringify({ mbti_type: r.type, scores: r.axisScores, dimension_details: dimDetails }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.message || "AI 分析失败");
      st.deep.aiText = data.analysis;
      saveDeepStore(st.deep.result, st.store.deep?.completedAt || Date.now());
    } catch(err) {
      notify("AI 分析失败", err.message, "error");
    } finally {
      st.deep.aiLoading = false;
      renderDeepModal();
    }
  };

  window.toggleHistoryPanel = function() {
    const panel = $id("dtHistoryPanel");
    if (!panel) return;
    panel.classList.add("hidden");
    panel.innerHTML = "";
  };

  /* ====================================================
   * 十一、卡片状态刷新
   * ==================================================== */

  function buildSbtiResultText(profile) {
    if (!profile) return "";
    const code = esc(profile.code || "SBTI");
    const title = esc(profile.title || profile.code || "已生成画像");
    const match = Number(profile.match || 0);
    const mode = esc(profile.mode || "你的主类型");
    const matchText = match > 0 ? (`匹配度 ${match}%`) : "已生成";
    return `<span class="dt-deep-type">${code}</span><span class="dt-deep-name">${matchText}</span><span class="dt-card-chip done">${mode}</span>`;
  }

  function refreshCards() {
    function applyStatus(el, done) {
      if (!el) return;
      el.textContent = done ? "已完成" : "未开始";
      el.className = done ? "assessment-status-chip done" : "assessment-status-chip";
    }

    function applyResultButtonState(id, enabled) {
      const button = $id(id);
      if (!button) return;
      button.disabled = !enabled;
      button.classList.toggle("opacity-50", !enabled);
      button.classList.toggle("cursor-not-allowed", !enabled);
    }

    // Friends
    const fStatus = $id("dtFriendsStatus");
    const fResult = $id("dtFriendsResult");
    if (fStatus && fResult) {
      const r = st.friends.result;
      if (r && r.winner) {
        applyStatus(fStatus, true);
        fResult.textContent = `结果：${FRIENDS_RESULTS[r.winner]?.name||r.winner}`;
        fResult.classList.remove("hidden");
        applyResultButtonState("dtFriendsResultBtn", true);
      } else {
        applyStatus(fStatus, false);
        fResult.classList.add("hidden");
        applyResultButtonState("dtFriendsResultBtn", false);
      }
    }
    // Inside Out
    const ioStatus = $id("dtIOStatus");
    const ioResult = $id("dtIOResult");
    if (ioStatus && ioResult) {
      const r = st.insideout.result;
      if (r && r.winner) {
        applyStatus(ioStatus, true);
        ioResult.textContent = `结果：${IO_RESULTS[r.winner]?.name||r.winner}`;
        ioResult.classList.remove("hidden");
        applyResultButtonState("dtIOResultBtn", true);
      } else {
        applyStatus(ioStatus, false);
        ioResult.classList.add("hidden");
        applyResultButtonState("dtIOResultBtn", false);
      }
    }
    // Deep MBTI
    const dpStatus = $id("dtDeepStatus");
    const dpResult = $id("dtDeepResult");
    if (dpStatus && dpResult) {
      const r = st.deep.result;
      if (r && r.completed) {
        applyStatus(dpStatus, true);
        dpResult.innerHTML = `<span class="dt-deep-type">${esc(r.type)}</span><span class="dt-deep-name">${esc(MBTI_NAMES[r.type]||"")}</span>`;
        dpResult.classList.remove("hidden");
        applyResultButtonState("dtDeepResultBtn", true);
      } else {
        applyStatus(dpStatus, false);
        dpResult.classList.add("hidden");
        applyResultButtonState("dtDeepResultBtn", false);
      }
    }

    // SBTI
    const sbtiStatus = $id("dtSBTIStatus");
    const sbtiResult = $id("dtSBTIResult");
    if (sbtiStatus && sbtiResult) {
      const profile = st.store?.sbti || normalizeSbtiResult(getSbtiProfile());
      if (profile && profile.completedAt) {
        applyStatus(sbtiStatus, true);
        sbtiResult.innerHTML = buildSbtiResultText(profile);
        sbtiResult.classList.remove("hidden");
        applyResultButtonState("dtSBTIResultBtn", true);
      } else {
        applyStatus(sbtiStatus, false);
        sbtiResult.classList.add("hidden");
        applyResultButtonState("dtSBTIResultBtn", false);
      }
    }
  }

  function deepClone(value) {
    try {
      return JSON.parse(JSON.stringify(value));
    } catch (_) {
      return null;
    }
  }

  function getQuestionsByType(type) {
    const safeType = sanitizeTestType(type);
    if (safeType === "friends") return deepClone(FRIENDS_Q) || [];
    if (safeType === "insideout") return deepClone(IO_Q) || [];
    if (safeType === "sbti") {
      if (!Array.isArray(st.sbti.order) || !st.sbti.order.length) {
        const shuffled = shuffleSbtiQuestions(SBTI_QUESTIONS);
        st.sbti.order = shuffled.map((item) => item.id);
        st.sbti.insertAt = Math.floor(Math.random() * shuffled.length) + 1;
      }
      const ordered = st.sbti.order
        .map((id) => SBTI_QUESTIONS.find((item) => item.id === id))
        .filter(Boolean);
      const insertAt = Math.min(ordered.length, Math.max(1, Number(st.sbti.insertAt || 1)));
      const visible = [...ordered.slice(0, insertAt), SBTI_ALWAYS_INCLUDED_SPECIAL_QUESTION, ...ordered.slice(insertAt)];
      return deepClone(visible) || [];
    }
    return deepClone(DEEP_Q) || [];
  }

  function getStoredResultByType(type) {
    loadStoredResults();
    const safeType = sanitizeTestType(type);
    if (safeType === "deep") return deepClone(st.store.deep) || null;
    if (safeType === "sbti") return deepClone(st.store.sbti) || null;
    return deepClone(st.store[safeType]) || null;
  }

  function getHistoryRunsSnapshot() {
    return [];
  }

  function computeResultByType(type, answers) {
    const safeType = sanitizeTestType(type);
    if (safeType === "friends") return computeFriendsFromAnswers(answers);
    if (safeType === "insideout") return computeIOFromAnswers(answers);
    if (safeType === "sbti") return computeSbtiFromAnswers(answers);
    return computeDeepFromAnswers(answers);
  }

  function saveResultByType(type, result, options) {
    const safeType = sanitizeTestType(type);
    const completedAt = Number(options?.completedAt || Date.now());
    if (safeType === "friends") {
      const normalized = result && result.winner ? {
        winner: String(result.winner || ""),
        scores: { ...(result.scores || {}) },
      } : computeFriendsFromAnswers(options?.answers || {});
      if (!normalized?.winner) return null;
      st.friends.result = normalized;
      saveFriendsStore(normalized, completedAt);
      refreshCards();
      return deepClone(st.store.friends);
    }
    if (safeType === "insideout") {
      const normalized = result && result.winner ? {
        winner: String(result.winner || ""),
        scores: { ...(result.scores || {}) },
      } : computeIOFromAnswers(options?.answers || {});
      if (!normalized?.winner) return null;
      st.insideout.result = normalized;
      saveInsideOutStore(normalized, completedAt);
      refreshCards();
      return deepClone(st.store.insideout);
    }
    if (safeType === "sbti") {
      const normalizedSbti = normalizeSbtiResult(result) || normalizeSbtiResult(computeSbtiFromAnswers(options?.answers || {}));
      if (!normalizedSbti) return null;
      st.sbti.result = { ...normalizedSbti };
      saveSbtiStore(normalizedSbti, completedAt);
      refreshCards();
      return deepClone(st.store.sbti);
    }
    const normalizedDeep = normalizeDeepResult(result);
    if (!normalizedDeep) return null;
    st.deep.result = { ...normalizedDeep };
    st.deep.aiText = typeof options?.aiText === "string" ? String(options.aiText) : "";
    saveDeepStore(normalizedDeep, completedAt);
    refreshCards();
    return deepClone(st.store.deep);
  }

  window.__DeepTestHubCore__ = {
    sanitizeTestType,
    getQuestionsByType,
    getLikertAnswers: () => deepClone(DEEP_ANSWERS) || [],
    getSbtiConditionalQuestion: () => deepClone(SBTI_CONDITIONAL_SPECIAL_QUESTION) || null,
    getResultPageUrl: resultPageUrl,
    getRunnerPageUrl: runnerPageUrl,
    getStoredResultByType,
    getHistoryRunsSnapshot,
    computeResultByType,
    saveResultByType,
    getMbtiNameMap: () => deepClone(MBTI_NAMES) || {},
    getMbtiDetail: async (type) => {
      const data = await _loadMbtiDetail();
      return deepClone(data[String(type || "").toUpperCase()]) || null;
    },
    getFriendsResultMeta: () => deepClone(FRIENDS_RESULTS) || {},
    getInsideOutResultMeta: () => deepClone(IO_RESULTS) || {},
  };

  /* ====================================================
   * 十二、初始化
   * ==================================================== */

  function consumeOpenTestParam() {
    try {
      const url = new URL(window.location.href);
      const openType = sanitizeTestType(url.searchParams.get("open_test") || "");
      if (!url.searchParams.get("open_test")) return null;
      url.searchParams.delete("open_test");
      window.history.replaceState({}, "", url.toString());
      return openType;
    } catch(_) {
      return null;
    }
  }

  function init() {
    loadHist();
    loadStoredResults();
    if (!st.store.deep?.result && st.hist.cur) {
      saveDeepStore(st.deep.result || buildDeepResultFromHist(st.hist.cur), st.hist.cur.savedAt);
    }
    refreshCards();
    window.addEventListener("app:auth-changed", () => {
      loadHist();
      loadStoredResults();
      refreshCards();
    });
    const openType = consumeOpenTestParam();
    if (openType) {
      if (openType === "friends") {
        st.friends = { idx: 0, ans: {}, result: null };
      } else if (openType === "insideout") {
        st.insideout = { idx: 0, ans: {}, result: null };
      } else if (openType === "deep") {
        st.deep = { idx: 0, ans: {}, result: null, aiText: null, aiLoading: false };
      }
      setTimeout(() => openDeepTestModal(openType), 0);
    }
  }

  document.addEventListener("DOMContentLoaded", init);

})();
