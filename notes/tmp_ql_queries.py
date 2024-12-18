all_mints_for_given_addr = """

query MyQuery {
  pools(where: {id: "0xb2cc224c1c9fee385f8ad6a55b4d94e92359dc59"}) {
    id
    mints(
      where: {origin: "0x83106205dD989fd5cd953dAb514158B1E04ca557"}
    ) {
      id
      sender
      owner
      transaction {
        id
      }
      origin
      amountUSD
      logIndex
    }
  }
}

"""

get_abi_from_athscan =
"""
curl "https://api.basescan.org/api?module=contract&action=getabi&address=0x51f290CCCD6a54Af00b38edDd59212dE068B8A4b&apikey=TNW322ET48F6IBT3A3RP6Z689FBHV3TMPR" | jq -r '.result'  | jq > resources/abis/aerodrome_sugar.json
"""


"""
query MyQuery {
  pools(where: {id: "0xb2cc224c1c9fee385f8ad6a55b4d94e92359dc59"}) {
    id
    mints(where: {origin: "0x83106205dD989fd5cd953dAb514158B1E04ca557"}) {
      id
      sender
      owner
      transaction {
        id
      }
      origin
      amountUSD
      logIndex
    }
  }
  closed: positions(where: {id: "3796958"}) {
    id
    owner
    collectedToken0
    collectedToken1
    collectedFeesToken0
    collectedFeesToken1
    depositedToken0
    depositedToken1
    feeGrowthInside0LastX128
    feeGrowthInside1LastX128
    liquidity
    withdrawnToken0
    withdrawnToken1
  }
  
  opened:   positions(where: {id: "3899989"}) {
    id
    owner
    collectedToken0
    collectedToken1
    collectedFeesToken0
    collectedFeesToken1
    depositedToken0
    depositedToken1
    feeGrowthInside0LastX128
    feeGrowthInside1LastX128
    liquidity
    withdrawnToken0
    withdrawnToken1
  }

  transactions(
    where: {mints_: {origin: "0x83106205dD989fd5cd953dAb514158B1E04ca557"}}
  ) {
    id
    mints {
      id
      amountUSD
    }
    burns {
      id
      amountUSD
    }
  }
}
"""