// Starting content for the guest page. Everything here can be changed in /admin
// (Apartmani and Sadržaj); this file is only used until the first save there.
// Texts are kept per language: hr, en, de, it. A missing language falls back to en, then hr.
const L = (hr, en, de, it) => ({ hr, en, de, it });

export const DEFAULT_HOST = {
  name: '',
  phone: '',
  email: '',
};

export const DEFAULT_APARTMENTS = [
  {
    id: 'a1',
    name: 'Apartman 1',
    address: 'Mali Lošinj',
    map: '',
    wifi_ssid: '',
    wifi_pass: '',
    checkin: '14:00',
    checkout: '10:00',
    phone: '',
    items: [
      {
        title: L('Dolazak i ključevi', 'Arrival and keys', 'Ankunft und Schlüssel', 'Arrivo e chiavi'),
        text: L(
          'Javite nam se kad krenete prema otoku pa vas dočekamo s ključevima.',
          'Let us know when you are on your way to the island and we will meet you with the keys.',
          'Geben Sie uns Bescheid, wenn Sie auf dem Weg zur Insel sind – wir erwarten Sie mit den Schlüsseln.',
          'Avvisateci quando siete in viaggio verso l\'isola e vi aspetteremo con le chiavi.'),
        link: '',
      },
      {
        title: L('Kućni red', 'House rules', 'Hausordnung', 'Regole della casa'),
        text: L(
          'Pušenje je dozvoljeno samo na terasi.\nNoćni mir od 22 do 7 sati.\nPri izlasku ugasite klimu i zatvorite prozore.',
          'Smoking only on the terrace.\nQuiet hours from 10 pm to 7 am.\nPlease switch off the air conditioning and close the windows when you go out.',
          'Rauchen nur auf der Terrasse.\nNachtruhe von 22 bis 7 Uhr.\nBitte beim Verlassen die Klimaanlage ausschalten und die Fenster schließen.',
          'Si può fumare solo in terrazza.\nSilenzio dalle 22 alle 7.\nQuando uscite spegnete il condizionatore e chiudete le finestre.'),
        link: '',
      },
      {
        title: L('Smeće i recikliranje', 'Rubbish and recycling', 'Müll und Recycling', 'Rifiuti e raccolta differenziata'),
        text: L(
          'Kontejneri za otpad, papir i plastiku nalaze se uz cestu blizu kuće.',
          'Bins for general waste, paper and plastic are by the road near the house.',
          'Container für Restmüll, Papier und Plastik stehen an der Straße nahe dem Haus.',
          'I cassonetti per indifferenziata, carta e plastica sono sulla strada vicino alla casa.'),
        link: '',
      },
      {
        title: L('Odlazak', 'Check-out', 'Abreise', 'Partenza'),
        text: L(
          'Na dan odlaska ostavite ključeve u apartmanu ili nam ih predajte osobno.',
          'On the day of departure leave the keys in the apartment or hand them to us.',
          'Am Abreisetag lassen Sie die Schlüssel in der Wohnung oder geben sie uns persönlich.',
          'Il giorno della partenza lasciate le chiavi nell\'appartamento o consegnatecele di persona.'),
        link: '',
      },
    ],
  },
];

export const DEFAULT_CONTENT = {
  sections: [
    {
      id: 'town',
      icon: '🏘',
      title: L('Mali Lošinj', 'Mali Lošinj', 'Mali Lošinj', 'Mali Lošinj'),
      items: [
        {
          title: L('Dobrodošli', 'Welcome', 'Willkommen', 'Benvenuti'),
          text: L(
            'Mali Lošinj je najveći grad na jadranskim otocima, smješten u dubokoj zaštićenoj uvali. Lošinj je klimatsko lječilište još od 1892. – borove šume i ljekovito bilje daju zraku poseban miris. Rivu i stari grad najljepše je obići predvečer.',
            'Mali Lošinj is the largest town on the Adriatic islands, set in a deep sheltered bay. Lošinj has been a climatic health resort since 1892 – pine forests and wild herbs give the air its special scent. The harbour and old town are loveliest in the evening.',
            'Mali Lošinj ist die größte Stadt auf den Adriainseln und liegt in einer tiefen, geschützten Bucht. Lošinj ist seit 1892 Luftkurort – Pinienwälder und Heilkräuter geben der Luft ihren besonderen Duft. Hafen und Altstadt sind am Abend am schönsten.',
            'Mali Lošinj è la città più grande delle isole adriatiche, in una baia profonda e riparata. Lošinj è località climatica dal 1892: pinete ed erbe aromatiche danno all\'aria un profumo speciale. Il porto e il centro storico sono più belli la sera.'),
          link: 'https://www.visitlosinj.hr',
        },
        {
          title: L('Muzej Apoksiomena', 'Apoxyomenos Museum', 'Apoxyomenos-Museum', 'Museo dell\'Apoxyomenos'),
          text: L(
            'Brončani kip grčkog sportaša star oko 2000 godina, izvađen iz mora kod Lošinja 1999. Muzej je na rivi.',
            'A bronze statue of a Greek athlete, about 2000 years old, raised from the sea near Lošinj in 1999. The museum is on the harbour front.',
            'Eine etwa 2000 Jahre alte Bronzestatue eines griechischen Athleten, 1999 bei Lošinj aus dem Meer geborgen. Das Museum liegt an der Hafenpromenade.',
            'Statua in bronzo di un atleta greco di circa 2000 anni fa, recuperata dal mare vicino a Lošinj nel 1999. Il museo è sul lungomare.'),
          link: '',
        },
        {
          title: L('Šetnica do Čikata', 'Walk to Čikat', 'Spaziergang nach Čikat', 'Passeggiata a Čikat'),
          text: L(
            'Obalna šetnica vodi od centra kroz borovu šumu do uvale Čikat, oko 30 minuta laganog hoda.',
            'A seaside path leads from the centre through the pine forest to Čikat bay, about a 30-minute easy walk.',
            'Ein Uferweg führt vom Zentrum durch den Pinienwald zur Bucht Čikat, etwa 30 Minuten gemütlicher Spaziergang.',
            'Un sentiero lungo il mare porta dal centro attraverso la pineta fino alla baia di Čikat, circa 30 minuti a piedi.'),
          link: '',
        },
      ],
    },
    {
      id: 'island',
      icon: '🏝',
      title: L('Otok Lošinj', 'Island of Lošinj', 'Insel Lošinj', 'Isola di Lošinj'),
      items: [
        {
          title: L('Veli Lošinj', 'Veli Lošinj', 'Veli Lošinj', 'Veli Lošinj'),
          text: L(
            'Slikovito mjesto 4 km jugoistočno, s malom lukom i uvalom Rovenska. Ondje je i Plavi svijet – centar za more i dupine.',
            'A picturesque village 4 km south-east, with a small harbour and Rovenska bay. Home of Blue World – the sea and dolphin centre.',
            'Malerischer Ort 4 km südöstlich mit kleinem Hafen und der Bucht Rovenska. Hier ist auch Blue World – das Meeres- und Delfinzentrum.',
            'Pittoresco paese a 4 km a sud-est, con un porticciolo e la baia di Rovenska. Qui si trova anche Blue World, il centro del mare e dei delfini.'),
          link: 'https://www.blue-world.org',
        },
        {
          title: L('Osor', 'Osor', 'Osor', 'Ossero'),
          text: L(
            'Drevni gradić na mjestu gdje se Cres i Lošinj gotovo dodiruju, s okretnim mostom preko kanala. Kamene ulice, skulpture i ljetni glazbeni festival.',
            'An ancient little town where Cres and Lošinj almost touch, with a swing bridge over the canal. Stone streets, sculptures and a summer music festival.',
            'Uraltes Städtchen dort, wo sich Cres und Lošinj fast berühren, mit einer Drehbrücke über den Kanal. Steingassen, Skulpturen und ein sommerliches Musikfestival.',
            'Antica cittadina dove Cres e Lošinj quasi si toccano, con un ponte girevole sul canale. Vie di pietra, sculture e un festival musicale estivo.'),
          link: '',
        },
        {
          title: L('Osoršćica', 'Osoršćica hike', 'Wanderung Osoršćica', 'Escursione sull\'Osoršćica'),
          text: L(
            'Planinarska staza iz Nerezina do vrha Televrina (588 m) s pogledom na cijeli Kvarner. Krenite rano ujutro i ponesite dosta vode.',
            'A hiking trail from Nerezine to Televrina peak (588 m) with views over the whole Kvarner. Start early in the morning and take plenty of water.',
            'Wanderweg von Nerezine auf den Gipfel Televrina (588 m) mit Blick über die ganze Kvarner-Bucht. Früh morgens starten und genug Wasser mitnehmen.',
            'Sentiero da Nerezine alla cima Televrina (588 m) con vista su tutto il Quarnero. Partite presto e portate molta acqua.'),
          link: '',
        },
        {
          title: L('Izleti brodom', 'Boat trips', 'Bootsausflüge', 'Gite in barca'),
          text: L(
            'S rive svaki dan polaze izleti na Susak (pješčani otok), Ilovik (otok cvijeća) i do skrivenih uvala.',
            'Every day boats leave the harbour for Susak (the sand island), Ilovik (the island of flowers) and hidden bays.',
            'Täglich fahren Boote vom Hafen nach Susak (die Sandinsel), Ilovik (die Blumeninsel) und zu versteckten Buchten.',
            'Ogni giorno dal porto partono gite per Susak (l\'isola di sabbia), Ilovik (l\'isola dei fiori) e baie nascoste.'),
          link: '',
        },
      ],
    },
    {
      id: 'beaches',
      icon: '🏖',
      title: L('Plaže', 'Beaches', 'Strände', 'Spiagge'),
      items: [
        {
          title: L('Čikat', 'Čikat', 'Čikat', 'Čikat'),
          text: L(
            'Najpoznatija uvala na otoku, u borovoj šumi oko 2 km od centra. Šljunak, plitko more, kafići i najam ležaljki i pedalina.',
            'The island\'s best-known bay, in the pine forest about 2 km from the centre. Pebbles, shallow water, cafés, sunbeds and pedalos to rent.',
            'Die bekannteste Bucht der Insel, im Pinienwald etwa 2 km vom Zentrum. Kies, flaches Wasser, Cafés, Liegen und Tretboote zu mieten.',
            'La baia più famosa dell\'isola, nella pineta a circa 2 km dal centro. Ghiaia, acqua bassa, bar, lettini e pedalò a noleggio.'),
          link: '',
        },
        {
          title: L('Sunčana uvala', 'Sunčana uvala', 'Sunčana uvala', 'Sunčana uvala'),
          text: L(
            'Mirna i plitka uvala južno od Čikata, odlična za obitelji s djecom.',
            'A calm, shallow bay south of Čikat, great for families with children.',
            'Ruhige, flache Bucht südlich von Čikat, ideal für Familien mit Kindern.',
            'Baia tranquilla e poco profonda a sud di Čikat, ideale per famiglie con bambini.'),
          link: '',
        },
        {
          title: L('Krivica', 'Krivica', 'Krivica', 'Krivica'),
          text: L(
            'Skrivena uvala tirkiznog mora, do nje pješice (oko 40 min) ili brodom. Nema kafića – ponesite vodu i hranu.',
            'A hidden bay with turquoise water, reached on foot (about 40 min) or by boat. No cafés – bring water and food.',
            'Versteckte Bucht mit türkisfarbenem Wasser, zu Fuß (ca. 40 Min.) oder mit dem Boot erreichbar. Keine Cafés – Wasser und Essen mitnehmen.',
            'Baia nascosta dall\'acqua turchese, raggiungibile a piedi (circa 40 min) o in barca. Niente bar: portate acqua e cibo.'),
          link: '',
        },
        {
          title: L('Susak', 'Susak', 'Susak', 'Susak'),
          text: L(
            'Otok od pijeska s dugim pješčanim plažama – idealan jednodnevni izlet brodom.',
            'An island made of sand with long sandy beaches – a perfect day trip by boat.',
            'Eine Insel aus Sand mit langen Sandstränden – ein idealer Tagesausflug mit dem Boot.',
            'Un\'isola di sabbia con lunghe spiagge sabbiose: perfetta per una gita in barca in giornata.'),
          link: '',
        },
        {
          title: L('Savjet', 'Tip', 'Tipp', 'Consiglio'),
          text: L(
            'Ponesite cipelice za kupanje (stijene i ježinci) i suncobran – mnoge su plaže prirodne, bez hlada.',
            'Bring water shoes (rocks and sea urchins) and a sunshade – many beaches are natural, without shade.',
            'Nehmen Sie Badeschuhe (Felsen und Seeigel) und einen Sonnenschirm mit – viele Strände sind naturbelassen, ohne Schatten.',
            'Portate scarpette da scoglio (rocce e ricci di mare) e un ombrellone: molte spiagge sono naturali, senz\'ombra.'),
          link: '',
        },
      ],
    },
    {
      id: 'food',
      icon: '🍽',
      title: L('Restorani', 'Restaurants', 'Restaurants', 'Ristoranti'),
      items: [
        {
          title: L('Deveron Gastro Pub – naša preporuka', 'Deveron Gastro Pub – our tip', 'Deveron Gastro Pub – unser Tipp', 'Deveron Gastro Pub – il nostro consiglio'),
          text: L(
            'Blizu luke, Ulica Vladimira Gortana 32. Svježa riba i plodovi mora, domaći ravioli i tjestenina, rižota, pašticada, pizza i doručak. Svaki dan 08–24 h.',
            'Near the harbour, Ulica Vladimira Gortana 32. Fresh fish and seafood, homemade ravioli and pasta, risotto, pašticada, pizza and breakfast. Open daily 8 am – midnight.',
            'Nahe dem Hafen, Ulica Vladimira Gortana 32. Frischer Fisch und Meeresfrüchte, hausgemachte Ravioli und Pasta, Risotto, Pašticada, Pizza und Frühstück. Täglich 8–24 Uhr.',
            'Vicino al porto, Ulica Vladimira Gortana 32. Pesce fresco e frutti di mare, ravioli e pasta fatti in casa, risotto, pašticada, pizza e colazione. Tutti i giorni 8–24.'),
          link: 'https://deveronpub.com',
        },
        {
          title: L('Lokalni okusi', 'Local flavours', 'Lokale Spezialitäten', 'Sapori locali'),
          text: L(
            'Probajte lošinjsku janjetinu, ribu s gradela, kvarnerske škampe, maslinovo ulje i med s otoka.',
            'Try Lošinj lamb, grilled fish, Kvarner scampi, olive oil and honey from the island.',
            'Probieren Sie Lošinj-Lamm, gegrillten Fisch, Kvarner-Scampi, Olivenöl und Honig von der Insel.',
            'Assaggiate l\'agnello di Lošinj, il pesce alla griglia, gli scampi del Quarnero, l\'olio d\'oliva e il miele dell\'isola.'),
          link: '',
        },
      ],
    },
    {
      id: 'useful',
      icon: 'ℹ️',
      title: L('Korisno', 'Useful', 'Nützliches', 'Informazioni utili'),
      items: [
        {
          title: L('Hitni brojevi', 'Emergency numbers', 'Notrufnummern', 'Numeri di emergenza'),
          text: L(
            '112 – sve hitne službe\n194 – hitna pomoć\n192 – policija\n193 – vatrogasci\n195 – spašavanje na moru',
            '112 – all emergencies\n194 – ambulance\n192 – police\n193 – fire brigade\n195 – sea rescue',
            '112 – alle Notfälle\n194 – Rettungsdienst\n192 – Polizei\n193 – Feuerwehr\n195 – Seenotrettung',
            '112 – tutte le emergenze\n194 – ambulanza\n192 – polizia\n193 – vigili del fuoco\n195 – soccorso in mare'),
          link: '',
        },
        {
          title: L('Trajekti i katamarani', 'Ferries and catamarans', 'Fähren und Katamarane', 'Traghetti e catamarani'),
          text: L(
            'Katamaran Mali Lošinj – Cres – Rijeka. Trajekti za otok Cres: Brestova – Porozina i Valbiska (Krk) – Merag. Ljeti na trajekt dođite ranije.',
            'Catamaran Mali Lošinj – Cres – Rijeka. Ferries to the island of Cres: Brestova – Porozina and Valbiska (Krk) – Merag. In summer arrive early for the ferry.',
            'Katamaran Mali Lošinj – Cres – Rijeka. Fähren zur Insel Cres: Brestova – Porozina und Valbiska (Krk) – Merag. Im Sommer früh zur Fähre kommen.',
            'Catamarano Mali Lošinj – Cres – Rijeka. Traghetti per l\'isola di Cres: Brestova – Porozina e Valbiska (Krk) – Merag. In estate arrivate presto al traghetto.'),
          link: 'https://www.jadrolinija.hr',
        },
        {
          title: L('Turistička zajednica', 'Tourist board', 'Tourismusverband', 'Ente del turismo'),
          text: L(
            'Događanja, izleti i karte otoka.',
            'Events, excursions and maps of the island.',
            'Veranstaltungen, Ausflüge und Karten der Insel.',
            'Eventi, escursioni e mappe dell\'isola.'),
          link: 'https://www.visitlosinj.hr',
        },
      ],
    },
  ],
};
