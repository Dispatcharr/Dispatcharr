import { createTheme, MantineProvider, rem } from '@mantine/core';

const theme = createTheme({
  globalStyles: (theme) => ({
    ':root': {
      '--mantine-color-text': '#fff',
      '--mantine-color-body': '#27272A',
      '--mrt-striped-row-background-color': '#fff',
    },
    ':root[data-mantine-color-scheme="dark"]': {
      '--mantine-color-text': '#fff',
    },
    ':root[data-mantine-color-scheme="light"]': {
      '--mantine-color-text': '#fff',
    },
  }),

  tailwind: {
    red: [
      'oklch(0.971 0.013 17.38)',
      'oklch(0.936 0.032 17.717)',
      'oklch(0.885 0.062 18.334)',
      'oklch(0.808 0.114 19.571)',
      'oklch(0.704 0.191 22.216)',
      'oklch(0.637 0.237 25.331)',
      'oklch(0.577 0.245 27.325)',
      'oklch(0.505 0.213 27.518)',
      'oklch(0.444 0.177 26.899)',
      'oklch(0.396 0.141 25.723)',
      'oklch(0.258 0.092 26.042)',
    ],
    orange: [
      'oklch(0.98 0.016 73.684)',
      'oklch(0.954 0.038 75.164)',
      'oklch(0.901 0.076 70.697)',
      'oklch(0.837 0.128 66.29)',
      'oklch(0.75 0.183 55.934)',
      'oklch(0.705 0.213 47.604)',
      'oklch(0.646 0.222 41.116)',
      'oklch(0.553 0.195 38.402)',
      'oklch(0.47 0.157 37.304)',
      'oklch(0.408 0.123 38.172)',
      'oklch(0.266 0.079 36.259)',
    ],
    amber: [
      'oklch(0.987 0.022 95.277)',
      'oklch(0.962 0.059 95.617)',
      'oklch(0.924 0.12 95.746)',
      'oklch(0.879 0.169 91.605)',
      'oklch(0.828 0.189 84.429)',
      'oklch(0.769 0.188 70.08)',
      'oklch(0.666 0.179 58.318)',
      'oklch(0.555 0.163 48.998)',
      'oklch(0.473 0.137 46.201)',
      'oklch(0.414 0.112 45.904)',
      'oklch(0.279 0.077 45.635)',
    ],
    yellow: [
      'oklch(0.987 0.026 102.212)',
      'oklch(0.973 0.071 103.193)',
      'oklch(0.945 0.129 101.54)',
      'oklch(0.905 0.182 98.111)',
      'oklch(0.852 0.199 91.936)',
      'oklch(0.795 0.184 86.047)',
      'oklch(0.681 0.162 75.834)',
      'oklch(0.554 0.135 66.442)',
      'oklch(0.476 0.114 61.907)',
      'oklch(0.421 0.095 57.708)',
      'oklch(0.286 0.066 53.813)',
    ],
    lime: [
      'oklch(0.986 0.031 120.757)',
      'oklch(0.967 0.067 122.328)',
      'oklch(0.938 0.127 124.321)',
      'oklch(0.897 0.196 126.665)',
      'oklch(0.841 0.238 128.85)',
      'oklch(0.768 0.233 130.85)',
      'oklch(0.648 0.2 131.684)',
      'oklch(0.532 0.157 131.589)',
      'oklch(0.453 0.124 130.933)',
      'oklch(0.405 0.101 131.063)',
      'oklch(0.274 0.072 132.109)',
    ],
    green: [
      'oklch(0.982 0.018 155.826)',
      'oklch(0.962 0.044 156.743)',
      'oklch(0.925 0.084 155.995)',
      'oklch(0.871 0.15 154.449)',
      'oklch(0.792 0.209 151.711)',
      'oklch(0.723 0.219 149.579)',
      'oklch(0.627 0.194 149.214)',
      'oklch(0.527 0.154 150.069)',
      'oklch(0.448 0.119 151.328)',
      'oklch(0.393 0.095 152.535)',
      'oklch(0.266 0.065 152.934)',
    ],
    emerald: [
      'oklch(0.979 0.021 166.113)',
      'oklch(0.95 0.052 163.051)',
      'oklch(0.905 0.093 164.15)',
      'oklch(0.845 0.143 164.978)',
      'oklch(0.765 0.177 163.223)',
      'oklch(0.696 0.17 162.48)',
      'oklch(0.596 0.145 163.225)',
      'oklch(0.508 0.118 165.612)',
      'oklch(0.432 0.095 166.913)',
      'oklch(0.378 0.077 168.94)',
      'oklch(0.262 0.051 172.552)',
    ],
    teal: [
      'oklch(0.984 0.014 180.72)',
      'oklch(0.953 0.051 180.801)',
      'oklch(0.91 0.096 180.426)',
      'oklch(0.855 0.138 181.071)',
      'oklch(0.777 0.152 181.912)',
      'oklch(0.704 0.14 182.503)',
      'oklch(0.6 0.118 184.704)',
      'oklch(0.511 0.096 186.391)',
      'oklch(0.437 0.078 188.216)',
      'oklch(0.386 0.063 188.416)',
      'oklch(0.277 0.046 192.524)',
    ],
    cyan: [
      'oklch(0.984 0.019 200.873)',
      'oklch(0.956 0.045 203.388)',
      'oklch(0.917 0.08 205.041)',
      'oklch(0.865 0.127 207.078)',
      'oklch(0.789 0.154 211.53)',
      'oklch(0.715 0.143 215.221)',
      'oklch(0.609 0.126 221.723)',
      'oklch(0.52 0.105 223.128)',
      'oklch(0.45 0.085 224.283)',
      'oklch(0.398 0.07 227.392)',
      'oklch(0.302 0.056 229.695)',
    ],
    sky: [
      'oklch(0.977 0.013 236.62)',
      'oklch(0.951 0.026 236.824)',
      'oklch(0.901 0.058 230.902)',
      'oklch(0.828 0.111 230.318)',
      'oklch(0.746 0.16 232.661)',
      'oklch(0.685 0.169 237.323)',
      'oklch(0.588 0.158 241.966)',
      'oklch(0.5 0.134 242.749)',
      'oklch(0.443 0.11 240.79)',
      'oklch(0.391 0.09 240.876)',
      'oklch(0.293 0.066 243.157)',
    ],
    blue: [
      'oklch(0.97 0.014 254.604)',
      'oklch(0.932 0.032 255.585)',
      'oklch(0.882 0.059 254.128)',
      'oklch(0.809 0.105 251.813)',
      'oklch(0.707 0.165 254.624)',
      'oklch(0.623 0.214 259.815)',
      'oklch(0.546 0.214 264.39)',
      'oklch(0.466 0.188 267.053)',
      'oklch(0.396 0.156 269.132)',
      'oklch(0.342 0.125 270.105)',
      'oklch(0.246 0.092 272.445)',
    ],
    indigo: [
      'oklch(0.938 0.015 268.693)',
      'oklch(0.901 0.036 269.522)',
      'oklch(0.843 0.072 267.564)',
      'oklch(0.761 0.12 264.179)',
      'oklch(0.652 0.159 267.585)',
      'oklch(0.573 0.194 271.68)',
      'oklch(0.492 0.205 275.687)',
      'oklch(0.418 0.179 278.963)',
      'oklch(0.357 0.145 282.163)',
      'oklch(0.305 0.112 283.928)',
      'oklch(0.213 0.078 287.434)',
    ],
  },

  palette: {
    mode: 'dark',
    background: {
      default: '#18181b', // Global background color (Tailwind zinc-900)
      paper: '#27272a', // Paper background (Tailwind zinc-800)
    },
    primary: {
      main: '#4A90E2',
      contrastText: '#FFFFFF',
    },
    secondary: {
      main: '#F5A623',
      contrastText: '#FFFFFF',
    },
    text: {
      primary: '#FFFFFF',
      secondary: '#d4d4d8', // Updated secondary text color (Tailwind zinc-300)
    },
    // Custom colors for components (chip buttons, borders, etc.)
    custom: {
      // For chip buttons:
      greenMain: '#90C43E',
      greenHoverBg: 'rgba(144,196,62,0.1)',

      indigoMain: '#4F39F6',
      indigoHoverBg: 'rgba(79,57,246,0.1)',

      greyBorder: '#707070',
      greyHoverBg: 'rgba(112,112,112,0.1)',
      greyText: '#a0a0a0',

      // Common border colors:
      borderDefault: '#3f3f46', // Tailwind zinc-700
      borderHover: '#5f5f66', // Approximate Tailwind zinc-600

      // For the "Add" button:
      successBorder: '#00a63e',
      successBg: '#0d542b',
      successBgHover: '#0a4020',
      successIcon: '#05DF72',
    },
  },

  custom: {
    colors: {
      buttonPrimary: '#14917E',
    },

    sidebar: {
      activeBackground: 'rgba(21, 69, 62, 0.67)',
      activeBorder: '#14917e',
      hoverBackground: '#27272a',
      hoverBorder: '#3f3f46',
      fontFamily: 'Inter, sans-serif',
    },
  },
});

export default theme;
