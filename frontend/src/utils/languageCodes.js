const ISO_639_2B_CODE_LIST =
  `aar abk ace ach ada ady afa afh afr ain aka akk alb ale alg alt amh ang anp apa ara arc arg arm arn arp art arw asm ast ath aus ava ave awa aym aze bad bai bak bal bam ban baq bas bat bej bel bem ben ber bho bih bik bin bis bla bnt bod bos bra bre btk bua bug bul bur byn cad cai car cat cau ceb cel cha chb che chg chi chk chm chn cho chp chr chu chv chy cmc cnr cop cor cos cpe cpf cpp cre crh crp csb cus cze dak dan dar day del den dgr din div doi dra dsb dua dum dut dyu dzo efi egy eka elx eng enm epo est ewe ewo fan fao fat fij fil fin fiu fon fre frm fro frr frs fry ful fur gaa gay gba gem geo ger gez gil gla gle glg glv gmh goh gon gor got grb grc gre grn gsw guj gwi hai hat hau haw heb her hil him hin hit hmn hmo hrv hsb hun hup iba ibo ice ido iii ijo iku ile ilo ina inc ind ine inh ipk ira iro ita jav jbo jpn jpr jrb kaa kab kac kal kam kan kar kas kau kaw kaz kbd kha khi khm kho kik kin kir kmb kok kom kon kor kos kpe krc krl kro kru kua kum kur kut lad lah lam lao lat lav lez lim lin lit lol loz ltz lua lub lug lui lun luo lus mac mad mag mah mai mak mal man mao map mar mas may mdf mdr men mga mic min mis mkh mlg mlt mnc mni mno moh mon mos mul mun mus mwl mwr myn myv nah nai nap nau nav nbl nde ndo nds nep new nia nic niu nno nob nog non nor nqo nso nub nwc nya nym nyn nyo nzi oci oji ori orm osa oss ota oto paa pag pal pam pan pap pau peo per phi phn pli pol pon por pra pro pus que raj rap rar roa roh rom rum run rup rus sad sag sah sai sal sam san sas sat scn sco sel sem sga sgn shn sid sin sio sit sla slo slv sma sme smi smj smn smo sms sna snd snk sog som son sot spa srd srn srp srr ssa ssw suk sun sus sux swa swe syc syr tah tai tam tat tel tem ter tet tgk tgl tha tib tig tir tiv tkl tlh tli tmh tog ton tpi tsi tsn tso tuk tum tup tur tut tvl twi tyv udm uga uig ukr umb und urd uzb vai ven vie vol vot wak wal war was wel wen wln wol xal yao yap yid yor ypk zap zbl zen zgh zha znd zul zun zxx`.split(
    ' '
  );
const ISO_639_2B_CODES = new Set(ISO_639_2B_CODE_LIST);

const COMMON_LANGUAGE_NAMES = {
  ara: 'Arabic',
  chi: 'Chinese',
  cze: 'Czech',
  dan: 'Danish',
  dut: 'Dutch',
  eng: 'English',
  fin: 'Finnish',
  fre: 'French',
  ger: 'German',
  gre: 'Greek',
  heb: 'Hebrew',
  hin: 'Hindi',
  hun: 'Hungarian',
  ice: 'Icelandic',
  ita: 'Italian',
  jpn: 'Japanese',
  kor: 'Korean',
  mul: 'Multiple languages',
  nor: 'Norwegian',
  per: 'Persian',
  pol: 'Polish',
  por: 'Portuguese',
  rum: 'Romanian',
  rus: 'Russian',
  spa: 'Spanish',
  swe: 'Swedish',
  tha: 'Thai',
  tur: 'Turkish',
  ukr: 'Ukrainian',
  und: 'Undetermined',
  vie: 'Vietnamese',
  zxx: 'No linguistic content',
};

export const LANGUAGE_OPTIONS = ISO_639_2B_CODE_LIST.filter(
  (code) => COMMON_LANGUAGE_NAMES[code]
)
  .map((code) => ({
    value: code,
    label: `${code.toUpperCase()} — ${COMMON_LANGUAGE_NAMES[code]}`,
  }))
  .sort((left, right) => left.label.localeCompare(right.label));

const LANGUAGE_ALIASES = {
  de: 'ger',
  deu: 'ger',
  german: 'ger',
  deutsch: 'ger',
  en: 'eng',
  english: 'eng',
  englisch: 'eng',
  fr: 'fre',
  fra: 'fre',
  french: 'fre',
  es: 'spa',
  spanish: 'spa',
  it: 'ita',
  italian: 'ita',
  nl: 'dut',
  nld: 'dut',
  dutch: 'dut',
};

export const normalizeLanguageCode = (value) => {
  const code = String(value || '')
    .trim()
    .toLowerCase();
  return LANGUAGE_ALIASES[code] || code;
};

export const normalizeLanguageCodes = (values) =>
  [
    ...new Set(
      (Array.isArray(values) ? values : []).map(normalizeLanguageCode)
    ),
  ].filter(Boolean);

export const invalidLanguageCodes = (values) =>
  normalizeLanguageCodes(values).filter((code) => !ISO_639_2B_CODES.has(code));

export const languageCodeError = (values) => {
  const invalid = invalidLanguageCodes(values);
  return invalid.length
    ? `Use ISO 639-2/B codes (for example ger, eng). Invalid: ${invalid.join(', ')}`
    : null;
};
