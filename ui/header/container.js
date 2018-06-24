import { connect } from 'react-redux'

import Header from './component'

import { setPage } from './actions'

const mapStateToProps = state => state.page

const mapDispatchToProps = dispatch => ({
  onPageChange: page => {
    dispatch(setPage(page))
    location.reload()
  }
})

export default connect(
  mapStateToProps,
  mapDispatchToProps
)(Header)