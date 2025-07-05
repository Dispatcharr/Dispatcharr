import logo from '../images/logo.png';

function Logo({ width = 30, showText = true }) {
  return (
    <>
      <img width={width} src={logo} />
      {showText && (
        <Text
          sx={{
            opacity: showText ? 1 : 0,
            transition: 'opacity 0.2s ease-in-out',
            whiteSpace: 'nowrap', // Ensures text never wraps
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            minWidth: showText ? 150 : 0, // Prevents reflow
          }}
        >
          Dispatcharr
        </Text>
      )}
    </>
  )
}

export default Logo
